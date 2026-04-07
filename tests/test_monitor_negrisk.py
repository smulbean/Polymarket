"""Tests for monitor.negrisk — NegRisk arbitrage scanner."""
from __future__ import annotations

import pytest

from monitor.models import MarketSnapshot
from monitor.negrisk import NegRiskScanner, _infer_group_label, scan_negrisk_arbitrage


def _negrisk_snap(
    market_id: str,
    yes_price: float,
    group_id: str = "group1",
    title: str = "",
) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        question=f"Will {title or market_id} win the race?",
        condition_id=f"cond_{market_id}",
        yes_token_id=f"yes_{market_id}",
        no_token_id=f"no_{market_id}",
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 4),
        volume=10_000.0,
        liquidity=5_000.0,
        end_date="2025-11-05T00:00:00Z",
        status="active",
        neg_risk=True,
        neg_risk_market_id=group_id,
        group_item_title=title or market_id,
    )


class TestNegRiskScanner:
    def test_finds_buy_all_yes_opportunity(self) -> None:
        # Sum = 0.25 + 0.20 + 0.15 = 0.60 → buy all YES, guaranteed $1
        markets = [
            _negrisk_snap("alice", 0.25),
            _negrisk_snap("bob", 0.20),
            _negrisk_snap("carol", 0.15),
        ]
        opps = scan_negrisk_arbitrage(markets, min_gap=0.02)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.action == "buy_all_yes"
        assert opp.yes_sum == pytest.approx(0.60)
        assert opp.cost_per_set == pytest.approx(0.60)
        assert opp.profit_per_set == pytest.approx(0.40)
        assert opp.roi == pytest.approx(0.40 / 0.60)

    def test_finds_buy_all_no_opportunity(self) -> None:
        # Sum = 0.40 + 0.35 + 0.35 = 1.10 → buy all NO
        markets = [
            _negrisk_snap("alice", 0.40),
            _negrisk_snap("bob", 0.35),
            _negrisk_snap("carol", 0.35),
        ]
        opps = scan_negrisk_arbitrage(markets, min_gap=0.02)
        assert len(opps) == 1
        assert opps[0].action == "buy_all_no"

    def test_no_opportunity_when_sum_near_one(self) -> None:
        # Sum ≈ 1.00 (within noise)
        markets = [
            _negrisk_snap("alice", 0.34),
            _negrisk_snap("bob", 0.33),
            _negrisk_snap("carol", 0.33),
        ]
        opps = scan_negrisk_arbitrage(markets, min_gap=0.02)
        assert len(opps) == 0

    def test_ignores_non_negrisk_markets(self) -> None:
        normal = MarketSnapshot(
            market_id="normal",
            question="Will X happen?",
            condition_id="c1",
            yes_token_id="y1",
            no_token_id="n1",
            yes_price=0.30,
            no_price=0.70,
            volume=0,
            liquidity=0,
            end_date="",
            status="active",
            neg_risk=False,
        )
        opps = scan_negrisk_arbitrage([normal], min_gap=0.01)
        assert opps == []

    def test_ignores_closed_markets(self) -> None:
        markets = [
            _negrisk_snap("alice", 0.25),
            MarketSnapshot(
                market_id="bob",
                question="Will bob win?",
                condition_id="c2",
                yes_token_id="y2",
                no_token_id="n2",
                yes_price=0.20,
                no_price=0.80,
                volume=0,
                liquidity=0,
                end_date="",
                status="closed",     # ← closed
                neg_risk=True,
                neg_risk_market_id="group1",
            ),
        ]
        opps = scan_negrisk_arbitrage(markets, min_gap=0.01)
        # Only 1 active market in the group → below min group size
        assert len(opps) == 0

    def test_multiple_groups_scanned_independently(self) -> None:
        g1 = [_negrisk_snap(f"g1_{i}", 0.10, group_id="g1") for i in range(3)]
        g2 = [_negrisk_snap(f"g2_{i}", 0.10, group_id="g2") for i in range(4)]
        opps = scan_negrisk_arbitrage(g1 + g2, min_gap=0.02)
        assert len(opps) == 2
        group_ids = {o.group_id for o in opps}
        assert "g1" in group_ids
        assert "g2" in group_ids

    def test_sorted_by_roi_descending(self) -> None:
        # Group A: 0.5 ROI, Group B: 0.2 ROI
        g_a = [_negrisk_snap(f"a{i}", 0.20, group_id="ga") for i in range(3)]
        g_b = [_negrisk_snap(f"b{i}", 0.28, group_id="gb") for i in range(3)]
        opps = scan_negrisk_arbitrage(g_a + g_b, min_gap=0.01)
        assert opps[0].roi >= opps[1].roi

    def test_min_gap_filter(self) -> None:
        # Sum = 0.97 → gap = 0.03
        markets = [_negrisk_snap(f"m{i}", 0.32, group_id="g1") for i in range(3)]
        # With min_gap=0.05 → should not flag
        assert scan_negrisk_arbitrage(markets, min_gap=0.05) == []
        # With min_gap=0.01 → should flag
        assert len(scan_negrisk_arbitrage(markets, min_gap=0.01)) == 1
