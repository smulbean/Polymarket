"""
Trade executor with guardrails.

SAFETY GUARANTEES
-----------------
1. ``dry_run=True`` is the default.  The executor will log what it
   *would* do but never touch real money unless ``dry_run`` is
   explicitly set to ``False`` via config / env.

2. Hard per-trade cap (``max_per_trade``, default $20).

3. Hard daily cap (``max_per_day``, default $50) — checked against the
   trade log for the current UTC day.

4. Minimum order size of 5 shares (Polymarket's floor).

5. Every attempted trade (including dry-run and rejected) is written to
   ``~/.polymarket/trades.jsonl`` with a ``dry_run`` flag.

The executor is intentionally dumb about strategy — it just validates
guardrails and calls the backend.  The caller (scanner / opportunity
finder) decides what to trade.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .backend import PolymarketBackend
from .config import Config
from .models import TradeRecord
from .storage import load_trades, now_iso, save_trade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Guardrail exceptions
# ---------------------------------------------------------------------------


class GuardrailError(Exception):
    """Raised when a trade would violate a configured guardrail."""


class DailyLimitError(GuardrailError):
    """Raised when the daily spend cap would be exceeded."""


class PerTradeLimitError(GuardrailError):
    """Raised when a single trade exceeds the per-trade cap."""


class MinSizeError(GuardrailError):
    """Raised when the order size is below the minimum."""


class DryRunError(GuardrailError):
    """Raised (informatively) when a trade is blocked by dry_run mode."""


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class Executor:
    """
    Validates guardrails and submits orders to the Polymarket CLOB.

    Parameters
    ----------
    config:
        Loaded Config object.  If None, ``Config.load()`` is called.
    backend:
        PolymarketBackend instance.  If None, a new one is created from config.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        backend: Optional[PolymarketBackend] = None,
    ) -> None:
        self.config = config or Config.load()
        self.backend = backend or PolymarketBackend(self.config)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute(
        self,
        token_id: str,
        outcome: str,
        side: str,
        price: float,
        size: float,
        market_id: str = "",
        market_question: str = "",
        condition_id: str = "",
        strategy: str = "manual",
    ) -> TradeRecord:
        """
        Validate guardrails and place a limit order.

        Parameters
        ----------
        token_id:
            The outcome token to trade (YES or NO ``token_id``).
        outcome:
            ``"YES"`` or ``"NO"`` — used for logging only.
        side:
            ``"buy"`` or ``"sell"``.
        price:
            Limit price between 0.01 and 0.99.
        size:
            Number of shares (minimum 5).
        strategy:
            Tag for the learning loop (e.g. ``"negrisk_arb"``).

        Returns
        -------
        TradeRecord
            A record of the trade attempt (regardless of dry_run status).

        Raises
        ------
        GuardrailError
            If any pre-trade check fails.
        RuntimeError
            If the backend rejects the order.
        """
        cost = price * size
        self._check_guardrails(cost, size)

        record = TradeRecord(
            timestamp=now_iso(),
            market_id=market_id,
            market_question=market_question,
            condition_id=condition_id,
            token_id=token_id,
            outcome=outcome.upper(),
            side=side.lower(),
            price=price,
            size=size,
            cost=round(cost, 6),
            strategy=strategy,
            status="open",
            dry_run=self.config.trading.dry_run,
        )

        if self.config.trading.dry_run:
            logger.info(
                "[DRY RUN] Would place %s %s order: %s @ %.4f × %.2f = $%.2f",
                side.upper(), outcome.upper(), market_question[:40], price, size, cost,
            )
            record.order_id = "DRY_RUN"
            save_trade(record.to_dict())
            return record

        # Live trade
        if not self.config.has_trading_credentials:
            raise RuntimeError(
                "Cannot place live order: trading credentials not configured.  "
                "Set POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS."
            )

        logger.info(
            "Placing LIVE %s %s order: %s @ %.4f × %.2f = $%.2f",
            side.upper(), outcome.upper(), market_question[:40], price, size, cost,
        )
        try:
            result = self.backend.place_order(
                token_id=token_id,
                price=price,
                size=size,
                side=side.upper(),
            )
            record.order_id = result.get("orderID", result.get("order_id", ""))
            record.status = "open"
        except Exception as exc:
            record.status = "failed"
            record.order_id = f"ERROR:{exc}"
            save_trade(record.to_dict())
            raise RuntimeError(f"Order placement failed: {exc}") from exc

        save_trade(record.to_dict())
        return record

    def execute_negrisk_arb(
        self,
        markets: List[Any],          # List[MarketSnapshot]
        sets: int = 1,
        strategy: str = "negrisk_arb",
    ) -> List[TradeRecord]:
        """
        Execute a NegRisk arbitrage: buy the YES token of every candidate.

        Parameters
        ----------
        markets:
            The MarketSnapshot objects in the NegRisk group.
        sets:
            Number of complete sets to buy.
        """
        records: List[TradeRecord] = []
        for market in markets:
            record = self.execute(
                token_id=market.yes_token_id,
                outcome="YES",
                side="buy",
                price=market.yes_price,
                size=max(float(sets), self.config.trading.min_shares),
                market_id=market.market_id,
                market_question=market.question,
                condition_id=market.condition_id,
                strategy=strategy,
            )
            records.append(record)
        return records

    def execute_near_resolution(
        self,
        opp: Any,  # NearResolutionOpportunity
        strategy: str = "near_resolution",
    ) -> Optional[TradeRecord]:
        """Execute a near-resolution trade."""
        market = opp.market
        outcome = opp.outcome  # "YES" or "NO"
        price = opp.price
        token_id = market.yes_token_id if outcome == "YES" else market.no_token_id
        size = max(self.config.trading.min_shares,
                   self.config.trading.max_per_trade / max(price, 0.01))
        size = min(size, self.config.trading.max_per_trade / max(price, 0.01))
        return self.execute(
            token_id=token_id,
            outcome=outcome,
            side="buy",
            price=price,
            size=round(size, 2),
            market_id=market.market_id,
            market_question=market.question,
            condition_id=market.condition_id,
            strategy=strategy,
        )

    def execute_claude_recommendation(
        self,
        market: Any,   # MarketSnapshot
        result: Any,   # AnalysisResult
        strategy: str = "conviction",
    ) -> Optional[TradeRecord]:
        """Execute a trade based on a Claude AnalysisResult."""
        if result.recommendation == "BUY_YES":
            token_id = market.yes_token_id
            outcome = "YES"
            price = market.yes_price
        elif result.recommendation == "BUY_NO":
            token_id = market.no_token_id
            outcome = "NO"
            price = market.no_price
        else:
            return None

        size = max(self.config.trading.min_shares,
                   self.config.trading.max_per_trade / max(price, 0.01))
        size = min(size, self.config.trading.max_per_trade / max(price, 0.01))
        return self.execute(
            token_id=token_id,
            outcome=outcome,
            side="buy",
            price=price,
            size=round(size, 2),
            market_id=market.market_id,
            market_question=market.question,
            condition_id=market.condition_id,
            strategy=strategy,
        )

    def cancel(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order by its exchange ID."""
        if self.config.trading.dry_run:
            logger.info("[DRY RUN] Would cancel order %s", order_id)
            return {"cancelled": order_id, "dry_run": True}
        return self.backend.cancel_order(order_id)

    # ------------------------------------------------------------------
    # Guardrail checks
    # ------------------------------------------------------------------

    def _check_guardrails(self, cost: float, size: float) -> None:
        tc = self.config.trading

        if size < tc.min_shares:
            raise MinSizeError(
                f"Order size {size:.2f} is below minimum {tc.min_shares:.2f} shares"
            )

        if cost > tc.max_per_trade:
            raise PerTradeLimitError(
                f"Trade cost ${cost:.2f} exceeds per-trade limit ${tc.max_per_trade:.2f}"
            )

        spent_today = self._daily_spend()
        if spent_today + cost > tc.max_per_day:
            raise DailyLimitError(
                f"Daily limit would be exceeded: already spent ${spent_today:.2f},"
                f" adding ${cost:.2f} would reach ${spent_today + cost:.2f}"
                f" (limit: ${tc.max_per_day:.2f})"
            )

    def _daily_spend(self) -> float:
        """Sum of costs for trades placed today (UTC), excluding dry-run trades."""
        today = datetime.now(timezone.utc).date().isoformat()
        total = 0.0
        for t in load_trades():
            ts = t.get("timestamp", "")[:10]
            if ts == today and not t.get("dry_run", True) and t.get("status") != "failed":
                total += float(t.get("cost", 0))
        return total

    def daily_summary(self) -> Dict[str, Any]:
        """Return a quick summary of today's trading activity."""
        today = datetime.now(timezone.utc).date().isoformat()
        trades = [
            t for t in load_trades()
            if t.get("timestamp", "")[:10] == today
        ]
        live = [t for t in trades if not t.get("dry_run", True)]
        return {
            "date": today,
            "total_trades": len(trades),
            "live_trades": len(live),
            "dry_run_trades": len(trades) - len(live),
            "spent_today": round(sum(float(t.get("cost", 0)) for t in live), 2),
            "daily_limit": self.config.trading.max_per_day,
            "remaining_today": round(
                self.config.trading.max_per_day - self._daily_spend(), 2
            ),
        }
