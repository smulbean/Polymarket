"""
Autonomous Polymarket background agent.

Runs a continuous scan-analyse-execute loop:

  Priority 1 — NegRisk arbitrage (guaranteed edge, no Claude needed)
  Priority 2 — Near-resolution opportunities (near-certain outcomes)
  Priority 3 — Claude-analysed markets (uncertain, 0.10–0.90 range)

Each cycle:
  1. Fetch active markets from Gamma API
  2. Scan NegRisk arbs → execute best ones (within guardrails)
  3. Scan near-resolution opportunities → execute
  4. Send uncertain markets to Claude for analysis → execute actionable ones
  5. Run reviewer to update won/lost trades and extract lessons
  6. Send Telegram cycle summary
  7. Sleep until next cycle
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from .analyst import MarketAnalyst
from .backend import PolymarketBackend
from .config import Config
from .executor import Executor, GuardrailError
from .models import MarketSnapshot
from .negrisk import NegRiskScanner
from .opportunities import find_near_resolution_opportunities
from .reviewer import run_reviewer
from .scanner import scan_bracket_arbitrage
from .telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class AgentCycleStats:
    """Lightweight stats accumulator for one agent cycle."""

    __slots__ = (
        "markets_fetched",
        "negrisk_opps", "negrisk_traded",
        "near_res_opps", "near_res_traded",
        "claude_analysed", "claude_traded",
        "errors",
    )

    def __init__(self) -> None:
        self.markets_fetched = 0
        self.negrisk_opps = 0
        self.negrisk_traded = 0
        self.near_res_opps = 0
        self.near_res_traded = 0
        self.claude_analysed = 0
        self.claude_traded = 0
        self.errors = 0

    @property
    def total_opportunities(self) -> int:
        return self.negrisk_opps + self.near_res_opps + self.claude_traded

    @property
    def total_traded(self) -> int:
        return self.negrisk_traded + self.near_res_traded + self.claude_traded


class PolymarketAgent:
    """
    Autonomous trading agent.

    Usage::

        cfg = Config.load()
        agent = PolymarketAgent(cfg)
        agent.run()          # blocks forever
        agent.run_once()     # single cycle (useful for testing)
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._backend = PolymarketBackend(cfg)
        self._executor = Executor(cfg, self._backend)
        self._negrisk = NegRiskScanner()
        self._notifier: Optional[TelegramNotifier] = (
            TelegramNotifier.from_config(cfg) if cfg.has_telegram else None
        )
        self._analyst: Optional[MarketAnalyst] = (
            MarketAnalyst.from_config(cfg) if cfg.has_claude_analyst else None
        )
        self._cycle_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run indefinitely, sleeping between cycles."""
        interval = self._cfg.agent.scan_interval_seconds
        logger.info("Agent starting — cycle interval %ds, dry_run=%s",
                    interval, self._cfg.trading.dry_run)
        if self._notifier:
            self._notifier.send_startup(self._cfg.trading.dry_run, interval)

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.info("Agent stopped by user")
                if self._notifier:
                    self._notifier.send_shutdown()
                break
            except Exception as exc:
                logger.error("Unhandled exception in agent cycle: %s", exc, exc_info=True)
                if self._notifier and self._cfg.notifications.notify_errors:
                    self._notifier.send_error("main loop", str(exc))
            time.sleep(interval)

    def run_once(self) -> AgentCycleStats:
        """Execute a single scan-analyse-execute cycle."""
        self._cycle_count += 1
        stats = AgentCycleStats()
        logger.info("=== Agent cycle #%d ===", self._cycle_count)

        # 1. Fetch markets
        markets = self._fetch_markets()
        stats.markets_fetched = len(markets)
        if not markets:
            logger.warning("No markets fetched — skipping cycle")
            return stats

        # 2. NegRisk arbitrage
        if self._cfg.agent.enable_negrisk_scan:
            self._run_negrisk(markets, stats)

        # 3. Near-resolution opportunities
        if self._cfg.agent.enable_near_resolution:
            self._run_near_resolution(markets, stats)

        # 4. Claude analysis on uncertain markets
        if self._cfg.agent.enable_claude_analysis and self._analyst:
            self._run_claude_analysis(markets, stats)

        # 5. Reviewer
        if self._cfg.agent.enable_reviewer:
            try:
                run_reviewer(self._cfg)
            except Exception as exc:
                logger.warning("Reviewer failed: %s", exc)
                stats.errors += 1

        # 6. Telegram summary
        if self._notifier and self._cfg.notifications.notify_cycle_summary:
            self._notifier.send_cycle_summary(
                cycle_num=self._cycle_count,
                opportunities=stats.total_opportunities,
                trades_placed=stats.total_traded,
                errors=stats.errors,
            )

        logger.info(
            "Cycle #%d done — %d markets, %d opps, %d trades, %d errors",
            self._cycle_count, stats.markets_fetched,
            stats.total_opportunities, stats.total_traded, stats.errors,
        )
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_markets(self) -> List[MarketSnapshot]:
        try:
            markets = self._backend.get_active_markets(
                limit=200,
                min_liquidity=self._cfg.agent.min_liquidity,
                resolution_window_days=self._cfg.agent.resolution_window_days,
            )
            logger.info("Fetched %d markets", len(markets))
            return markets
        except Exception as exc:
            logger.error("Failed to fetch markets: %s", exc)
            return []

    def _run_negrisk(self, markets: List[MarketSnapshot], stats: AgentCycleStats) -> None:
        try:
            opps = self._negrisk.scan(markets)
            stats.negrisk_opps = len(opps)
            logger.info("NegRisk: %d opportunities", len(opps))
            for opp in opps:
                try:
                    trades = self._executor.execute_negrisk_arb(opp.markets)
                    if trades:
                        stats.negrisk_traded += 1
                        if self._notifier and self._cfg.notifications.notify_trades:
                            for trade in trades:
                                self._notifier.send_trade_alert(trade.to_dict())
                except GuardrailError as e:
                    logger.info("NegRisk trade blocked by guardrail: %s", e)
                except Exception as exc:
                    logger.error("NegRisk execution error: %s", exc)
                    stats.errors += 1
        except Exception as exc:
            logger.error("NegRisk scan failed: %s", exc)
            stats.errors += 1

    def _run_near_resolution(
        self, markets: List[MarketSnapshot], stats: AgentCycleStats
    ) -> None:
        try:
            opps = find_near_resolution_opportunities(
                markets,
                hours_window=float(self._cfg.monitor.near_resolution_hours),
                min_confidence=self._cfg.monitor.near_resolution_min_confidence,
            )
            stats.near_res_opps = len(opps)
            logger.info("Near-resolution: %d opportunities", len(opps))
            for opp in opps:
                try:
                    trade = self._executor.execute_near_resolution(opp)
                    if trade:
                        stats.near_res_traded += 1
                        if self._notifier and self._cfg.notifications.notify_trades:
                            self._notifier.send_trade_alert(trade.to_dict())
                except GuardrailError as e:
                    logger.info("Near-resolution trade blocked by guardrail: %s", e)
                except Exception as exc:
                    logger.error("Near-resolution execution error: %s", exc)
                    stats.errors += 1
        except Exception as exc:
            logger.error("Near-resolution scan failed: %s", exc)
            stats.errors += 1

    def _run_claude_analysis(
        self, markets: List[MarketSnapshot], stats: AgentCycleStats
    ) -> None:
        # Filter to uncertain markets in the configured price band
        uncertain = [
            m for m in markets
            if self._cfg.agent.price_min <= m.yes_price <= self._cfg.agent.price_max
        ]
        max_calls = self._cfg.agent.max_markets_per_cycle
        logger.info("Claude: analysing %d/%d uncertain markets (cap=%d)",
                    min(len(uncertain), max_calls), len(uncertain), max_calls)
        try:
            results = self._analyst.analyse_batch(uncertain, max_calls=max_calls)
            stats.claude_analysed = min(len(uncertain), max_calls)
            logger.info("Claude: %d actionable results", len(results))
            for result in results:
                # Find the corresponding market snapshot
                market = next(
                    (m for m in uncertain if m.market_id == result.market_id), None
                )
                if market is None:
                    continue
                try:
                    trade = self._executor.execute_claude_recommendation(market, result)
                    if trade:
                        stats.claude_traded += 1
                        if self._notifier and self._cfg.notifications.notify_trades:
                            self._notifier.send_trade_alert(trade.to_dict())
                except GuardrailError as e:
                    logger.info("Claude trade blocked by guardrail: %s", e)
                except Exception as exc:
                    logger.error("Claude execution error: %s", exc)
                    stats.errors += 1
        except Exception as exc:
            logger.error("Claude analysis failed: %s", exc)
            stats.errors += 1
