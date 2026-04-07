"""Tests for monitor.scanner — bracket arbitrage scanner."""
from __future__ import annotations

import pytest

from monitor.models import MarketSnapshot
from monitor.scanner import _extract_threshold, scan_bracket_arbitrage


def _snap(market_id: str, question: str, yes_price: float, event_id: str = "evt1") -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        question=question,
        condition_id=f"cond_{market_id}",
        yes_token_id=f"yes_{market_id}",
        no_token_id=f"no_{market_id}",
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 4),
        volume=50_000.0,
        liquidity=10_000.0,
        end_date="2025-03-31T00:00:00Z",
        status="active",
        event_id=event_id,
    )


class TestExtractThreshold:
    @pytest.mark.parametrize("question,expected", [
        ("Will BTC exceed $68,000 by March?", 68_000),
        ("Will BTC reach $100k in 2025?", 100_000),
        ("ETH above $3,500 on December 31", 3_500),
        ("Will SOL hit $200?", 200),
        ("Gold above $2,500/oz", 2_500),
    ])
    def test_extracts_threshold(self, question: str, expected: float) -> None:
        assert _extract_threshold(question) == pytest.approx(expected)

    def test_returns_none_for_no_large_number(self) -> None:
        assert _extract_threshold("Will it rain tomorrow?") is None

    def test_ignores_small_numbers_like_years(self) -> None:
        result = _extract_threshold("Will BTC hit $75,000 in 2025?")
        # Should return 75,000 (largest number above 1000), not 2025
        assert result == pytest.approx(75_000)


class TestBracketScanner:
    def test_detects_monotonicity_violation(self) -> None:
        markets = [
            _snap("m_68k", "Will BTC exceed $68,000 by March?", yes_price=0.65),
            _snap("m_70k", "Will BTC exceed $70,000 by March?", yes_price=0.71),  # VIOLATION
            _snap("m_72k", "Will BTC exceed $72,000 by March?", yes_price=0.50),
        ]
        opps = scan_bracket_arbitrage(markets)
        violations = [o for o in opps if o.violation_type == "monotonicity"]
        assert len(violations) >= 1
        assert any(
            o.lower_market.market_id == "m_68k" and o.higher_market.market_id == "m_70k"
            for o in violations
        )

    def test_no_violation_when_monotone(self) -> None:
        markets = [
            _snap("m_68k", "Will BTC exceed $68,000 by March?", yes_price=0.72),
            _snap("m_70k", "Will BTC exceed $70,000 by March?", yes_price=0.65),
            _snap("m_72k", "Will BTC exceed $72,000 by March?", yes_price=0.50),
        ]
        violations = [
            o for o in scan_bracket_arbitrage(markets)
            if o.violation_type == "monotonicity"
        ]
        assert len(violations) == 0

    def test_detects_stale_extreme_high(self) -> None:
        markets = [
            _snap("m_low", "Will BTC exceed $10,000 by March?", yes_price=0.999),
            _snap("m_high", "Will BTC exceed $50,000 by March?", yes_price=0.60),
        ]
        opps = scan_bracket_arbitrage(markets)
        stale = [o for o in opps if o.violation_type == "stale_extreme"]
        assert len(stale) >= 1

    def test_groups_by_event_id(self) -> None:
        # Markets in two separate events should be analyzed independently.
        evt_a = [
            _snap("a1", "Will Gold exceed $2,000?", yes_price=0.80, event_id="evt_a"),
            _snap("a2", "Will Gold exceed $2,500?", yes_price=0.85, event_id="evt_a"),  # violation
        ]
        evt_b = [
            _snap("b1", "Will Silver exceed $25?", yes_price=0.70, event_id="evt_b"),
            _snap("b2", "Will Silver exceed $30?", yes_price=0.60, event_id="evt_b"),
        ]
        opps = scan_bracket_arbitrage(evt_a + evt_b)
        # Only event_a should have a violation
        violation_events = {o.event_id for o in opps if o.violation_type == "monotonicity"}
        assert "evt_a" in violation_events
        assert "evt_b" not in violation_events

    def test_ignores_markets_without_event_id(self) -> None:
        markets = [
            MarketSnapshot(
                market_id="orphan",
                question="Will BTC exceed $80,000?",
                condition_id="c1",
                yes_token_id="y1",
                no_token_id="n1",
                yes_price=0.50,
                no_price=0.50,
                volume=0,
                liquidity=0,
                end_date="",
                status="active",
                event_id=None,    # no event
            )
        ]
        opps = scan_bracket_arbitrage(markets)
        assert opps == []

    def test_sorted_by_edge_descending(self) -> None:
        markets = [
            _snap("m_50k", "Will BTC exceed $50,000 by March?", yes_price=0.60),
            _snap("m_60k", "Will BTC exceed $60,000 by March?", yes_price=0.80),  # big violation
            _snap("m_70k", "Will BTC exceed $70,000 by March?", yes_price=0.55),
        ]
        opps = scan_bracket_arbitrage(markets)
        if len(opps) >= 2:
            assert opps[0].estimated_edge >= opps[1].estimated_edge
