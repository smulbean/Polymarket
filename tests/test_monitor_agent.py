"""Tests for monitor.agent — autonomous orchestrator cycle."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from monitor.agent import AgentCycleStats, PolymarketAgent
from monitor.config import Config
from monitor.models import (
    MarketSnapshot,
    NearResolutionOpportunity,
    NegRiskOpportunity,
)


def _make_market(market_id: str = "m1", yes_price: float = 0.45) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        question=f"Test market {market_id}?",
        condition_id="c1",
        yes_token_id="yes1",
        no_token_id="no1",
        yes_price=yes_price,
        no_price=1 - yes_price,
        volume=50_000.0,
        liquidity=20_000.0,
        end_date="2025-12-31",
        status="active",
        neg_risk=False,
    )


def _make_config() -> Config:
    cfg = Config()
    cfg.trading.dry_run = True
    cfg.agent.enable_negrisk_scan = False
    cfg.agent.enable_near_resolution = False
    cfg.agent.enable_claude_analysis = False
    cfg.agent.enable_reviewer = False
    return cfg


class TestAgentCycleStats:
    def test_total_opportunities(self) -> None:
        s = AgentCycleStats()
        s.negrisk_opps = 2
        s.near_res_opps = 1
        s.claude_traded = 1
        assert s.total_opportunities == 4

    def test_total_traded(self) -> None:
        s = AgentCycleStats()
        s.negrisk_traded = 1
        s.near_res_traded = 2
        s.claude_traded = 1
        assert s.total_traded == 4


class TestPolymarketAgent:
    def _make_agent(self, cfg: Config) -> PolymarketAgent:
        with patch("monitor.agent.PolymarketBackend"), \
             patch("monitor.agent.Executor"):
            return PolymarketAgent(cfg)

    def test_run_once_returns_stats(self) -> None:
        cfg = _make_config()
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.return_value = [_make_market()]
        stats = agent.run_once()
        assert isinstance(stats, AgentCycleStats)
        assert stats.markets_fetched == 1

    def test_run_once_empty_markets(self) -> None:
        cfg = _make_config()
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.return_value = []
        stats = agent.run_once()
        assert stats.markets_fetched == 0
        assert stats.total_traded == 0

    def test_run_once_fetch_error_returns_zero_stats(self) -> None:
        cfg = _make_config()
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.side_effect = ConnectionError("timeout")
        stats = agent.run_once()
        assert stats.markets_fetched == 0

    def test_negrisk_scan_disabled_skips(self) -> None:
        cfg = _make_config()
        cfg.agent.enable_negrisk_scan = False
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.return_value = [_make_market()]

        with patch("monitor.agent.NegRiskScanner") as mock_scanner_cls:
            stats = agent.run_once()

        assert stats.negrisk_opps == 0

    def test_near_resolution_enabled_calls_finder(self) -> None:
        cfg = _make_config()
        cfg.agent.enable_near_resolution = True
        agent = self._make_agent(cfg)
        markets = [_make_market()]
        agent._backend.get_active_markets.return_value = markets

        with patch("monitor.agent.find_near_resolution_opportunities", return_value=[]) as mock_finder:
            agent.run_once()

        mock_finder.assert_called_once()

    def test_claude_analysis_skipped_without_analyst(self) -> None:
        cfg = _make_config()
        cfg.agent.enable_claude_analysis = True
        agent = self._make_agent(cfg)
        agent._analyst = None  # No API key configured
        agent._backend.get_active_markets.return_value = [_make_market()]
        stats = agent.run_once()
        assert stats.claude_analysed == 0

    def test_claude_analysis_filters_by_price_band(self) -> None:
        cfg = _make_config()
        cfg.agent.enable_claude_analysis = True
        cfg.agent.price_min = 0.10
        cfg.agent.price_max = 0.90
        agent = self._make_agent(cfg)
        agent._analyst = MagicMock()
        agent._analyst.analyse_batch.return_value = []

        markets = [
            _make_market("cheap", yes_price=0.02),   # below min → filtered
            _make_market("mid", yes_price=0.50),      # in band
            _make_market("certain", yes_price=0.98),  # above max → filtered
        ]
        agent._backend.get_active_markets.return_value = markets

        agent.run_once()

        called_markets = agent._analyst.analyse_batch.call_args[0][0]
        assert len(called_markets) == 1
        assert called_markets[0].market_id == "mid"

    def test_telegram_not_called_when_not_configured(self) -> None:
        cfg = _make_config()
        agent = self._make_agent(cfg)
        agent._notifier = None
        agent._backend.get_active_markets.return_value = []
        # Should not raise
        agent.run_once()

    def test_cycle_count_increments(self) -> None:
        cfg = _make_config()
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.return_value = []
        agent.run_once()
        agent.run_once()
        assert agent._cycle_count == 2

    def test_reviewer_errors_increment_error_count(self) -> None:
        cfg = _make_config()
        cfg.agent.enable_reviewer = True
        agent = self._make_agent(cfg)
        agent._backend.get_active_markets.return_value = [_make_market()]

        with patch("monitor.agent.run_reviewer", side_effect=RuntimeError("db error")):
            stats = agent.run_once()

        assert stats.errors == 1
