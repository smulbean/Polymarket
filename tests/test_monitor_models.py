"""Tests for monitor.models — construction and serialisation."""
from __future__ import annotations

import pytest

from monitor.models import (
    AlertRule,
    BracketOpportunity,
    MarketSnapshot,
    NearResolutionOpportunity,
    NegRiskOpportunity,
    StrategyScore,
    TradeRecord,
)


# ---------------------------------------------------------------------------
# MarketSnapshot
# ---------------------------------------------------------------------------


def _snap(**kwargs) -> MarketSnapshot:
    defaults = dict(
        market_id="m1",
        question="Will X happen?",
        condition_id="cond1",
        yes_token_id="tok_yes",
        no_token_id="tok_no",
        yes_price=0.45,
        no_price=0.55,
        volume=1_000_000.0,
        liquidity=100_000.0,
        end_date="2025-12-31T00:00:00Z",
        status="active",
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


class TestMarketSnapshot:
    def test_to_dict_roundtrip(self) -> None:
        snap = _snap(neg_risk=True, neg_risk_market_id="grp1")
        d = snap.to_dict()
        assert d["market_id"] == "m1"
        assert d["neg_risk"] is True

    def test_from_dict(self) -> None:
        snap = _snap()
        restored = MarketSnapshot.from_dict(snap.to_dict())
        assert restored.market_id == snap.market_id
        assert restored.yes_price == snap.yes_price


# ---------------------------------------------------------------------------
# TradeRecord
# ---------------------------------------------------------------------------


class TestTradeRecord:
    def test_defaults(self) -> None:
        t = TradeRecord()
        assert t.dry_run is True
        assert t.side == "buy"
        assert len(t.trade_id) == 8

    def test_to_dict_from_dict_roundtrip(self) -> None:
        t = TradeRecord(
            market_id="m1",
            outcome="YES",
            price=0.45,
            size=100.0,
            cost=45.0,
            strategy="negrisk_arb",
        )
        restored = TradeRecord.from_dict(t.to_dict())
        assert restored.market_id == "m1"
        assert restored.strategy == "negrisk_arb"
        assert restored.cost == 45.0


# ---------------------------------------------------------------------------
# AlertRule
# ---------------------------------------------------------------------------


class TestAlertRule:
    def test_above_fires(self) -> None:
        rule = AlertRule(market_id="m1", field="yes_price", operator="above", threshold=0.50)
        snap = _snap(yes_price=0.60)
        assert rule.evaluate(snap) is True

    def test_above_does_not_fire_below_threshold(self) -> None:
        rule = AlertRule(market_id="m1", field="yes_price", operator="above", threshold=0.80)
        snap = _snap(yes_price=0.60)
        assert rule.evaluate(snap) is False

    def test_below_fires(self) -> None:
        rule = AlertRule(market_id="m1", field="no_price", operator="below", threshold=0.30)
        snap = _snap(no_price=0.20)
        assert rule.evaluate(snap) is True

    def test_wrong_market_id_still_evaluates_on_values(self) -> None:
        # AlertRule.evaluate only looks at the snapshot values; filtering by
        # market_id is the monitor's responsibility.
        rule = AlertRule(market_id="OTHER", field="yes_price", operator="above", threshold=0.40)
        snap = _snap(yes_price=0.50)
        assert rule.evaluate(snap) is True


# ---------------------------------------------------------------------------
# StrategyScore
# ---------------------------------------------------------------------------


class TestStrategyScore:
    def test_win_rate_zero_trades(self) -> None:
        s = StrategyScore(strategy="test")
        assert s.win_rate == 0.0

    def test_win_rate_computed(self) -> None:
        s = StrategyScore(strategy="test", total_trades=4, wins=3, losses=1)
        assert s.win_rate == pytest.approx(0.75)

    def test_roi_computed(self) -> None:
        s = StrategyScore(strategy="test", invested=100.0, pnl=36.2, total_trades=3)
        assert s.roi == pytest.approx(0.362)

    def test_roi_zero_invested(self) -> None:
        s = StrategyScore(strategy="test")
        assert s.roi == 0.0

    def test_to_dict_contains_derived_fields(self) -> None:
        s = StrategyScore(strategy="negrisk_arb", total_trades=3, wins=3, invested=10.0, pnl=3.6)
        d = s.to_dict()
        assert "win_rate" in d
        assert "roi" in d
        assert d["win_rate"] == pytest.approx(1.0)
