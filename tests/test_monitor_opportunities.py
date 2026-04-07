"""Tests for monitor.opportunities — near-resolution finder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from monitor.models import MarketSnapshot
from monitor.opportunities import _hours_until, find_near_resolution_opportunities


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snap(
    yes_price: float,
    hours_ahead: float,
    status: str = "active",
) -> MarketSnapshot:
    end = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return MarketSnapshot(
        market_id=f"m_{hours_ahead}_{yes_price}",
        question="Will X happen?",
        condition_id="c1",
        yes_token_id="y1",
        no_token_id="n1",
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 4),
        volume=10_000.0,
        liquidity=5_000.0,
        end_date=_iso(end),
        status=status,
    )


class TestHoursUntil:
    def test_future_date(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        result = _hours_until(_iso(future))
        assert result == pytest.approx(5.0, abs=0.1)

    def test_past_date_negative(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        result = _hours_until(_iso(past))
        assert result is not None and result < 0

    def test_empty_string_returns_none(self) -> None:
        assert _hours_until("") is None

    def test_unparseable_returns_none(self) -> None:
        assert _hours_until("not-a-date") is None


class TestFindOpportunities:
    def test_finds_high_confidence_near_resolution(self) -> None:
        markets = [_snap(yes_price=0.95, hours_ahead=6)]
        opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)
        assert len(opps) == 1
        assert opps[0].outcome == "YES"
        assert opps[0].confidence == "HIGH"

    def test_finds_no_side_opportunity(self) -> None:
        # NO is at 0.93, YES at 0.07
        markets = [_snap(yes_price=0.07, hours_ahead=10)]
        opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)
        # NO price = 0.93 → should appear as a NO opportunity
        no_opps = [o for o in opps if o.outcome == "NO"]
        assert len(no_opps) == 1
        assert no_opps[0].price == pytest.approx(0.93)

    def test_excludes_market_outside_window(self) -> None:
        markets = [_snap(yes_price=0.95, hours_ahead=48)]  # 48h > 24h window
        opps = find_near_resolution_opportunities(markets, hours_window=24)
        assert len(opps) == 0

    def test_excludes_low_confidence_market(self) -> None:
        markets = [_snap(yes_price=0.75, hours_ahead=6)]  # 75c < 90c threshold
        opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)
        assert len(opps) == 0

    def test_excludes_closed_markets(self) -> None:
        markets = [_snap(yes_price=0.99, hours_ahead=1, status="closed")]
        opps = find_near_resolution_opportunities(markets)
        assert len(opps) == 0

    def test_sorted_high_confidence_first(self) -> None:
        markets = [
            _snap(yes_price=0.92, hours_ahead=5),   # MEDIUM (< 0.95)
            _snap(yes_price=0.97, hours_ahead=10),  # HIGH
        ]
        opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)
        assert opps[0].confidence == "HIGH"

    def test_roi_calculation(self) -> None:
        # Entry at 0.95 → ROI = (1 - 0.95) / 0.95 ≈ 5.26%
        markets = [_snap(yes_price=0.95, hours_ahead=2)]
        opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)
        assert len(opps) >= 1
        assert opps[0].roi == pytest.approx(0.05 / 0.95, rel=0.01)
