"""Tests for monitor.reviewer — strategy scoring and lesson extraction."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

import pytest

from monitor.models import StrategyScore
from monitor.reviewer import (
    _format_scorecard,
    compute_strategy_scores,
    extract_lessons,
)


def _resolved(strategy: str, won: bool, cost: float = 10.0) -> Dict:
    pnl = cost if won else -cost
    return {
        "trade_id": f"t_{strategy}_{won}",
        "strategy": strategy,
        "status": "won" if won else "lost",
        "cost": cost,
        "pnl": pnl,
        "dry_run": False,
    }


class TestComputeStrategyScores:
    def test_ignores_open_trades(self) -> None:
        trades = [{"strategy": "negrisk_arb", "status": "open", "cost": 10.0, "pnl": 0.0}]
        scores = compute_strategy_scores(trades)
        assert scores == {}

    def test_aggregates_wins_and_losses(self) -> None:
        trades = [
            _resolved("negrisk_arb", won=True, cost=5.0),
            _resolved("negrisk_arb", won=True, cost=5.0),
            _resolved("negrisk_arb", won=False, cost=5.0),
        ]
        scores = compute_strategy_scores(trades)
        s = scores["negrisk_arb"]
        assert s.total_trades == 3
        assert s.wins == 2
        assert s.losses == 1
        assert s.invested == pytest.approx(15.0)

    def test_multiple_strategies(self) -> None:
        trades = [
            _resolved("negrisk_arb", True),
            _resolved("near_resolution", True),
            _resolved("conviction", False),
        ]
        scores = compute_strategy_scores(trades)
        assert len(scores) == 3
        assert "negrisk_arb" in scores
        assert "near_resolution" in scores

    def test_pnl_summed_correctly(self) -> None:
        trades = [
            _resolved("test", True, cost=10.0),   # pnl = +10
            _resolved("test", False, cost=5.0),   # pnl = -5
        ]
        scores = compute_strategy_scores(trades)
        assert scores["test"].pnl == pytest.approx(5.0)


class TestExtractLessons:
    def test_high_win_rate_generates_lesson(self) -> None:
        s = StrategyScore(
            strategy="negrisk_arb",
            total_trades=5,
            wins=5,
            losses=0,
            invested=50.0,
            pnl=18.0,
        )
        lessons = extract_lessons({"negrisk_arb": s}, [])
        assert any("negrisk_arb" in lesson for lesson in lessons)

    def test_low_win_rate_generates_warning_lesson(self) -> None:
        s = StrategyScore(
            strategy="conviction",
            total_trades=5,
            wins=1,
            losses=4,
            invested=50.0,
            pnl=-20.0,
        )
        lessons = extract_lessons({"conviction": s}, [])
        assert any("underperforming" in lesson.lower() or "conviction" in lesson for lesson in lessons)

    def test_no_lessons_from_single_trade(self) -> None:
        s = StrategyScore(
            strategy="test",
            total_trades=1,
            wins=1,
            invested=10.0,
            pnl=5.0,
        )
        lessons = extract_lessons({"test": s}, [])
        # Not enough data to draw conclusions
        assert not any("test" in l and "best" in l for l in lessons)

    def test_best_strategy_identified(self) -> None:
        scores = {
            "a": StrategyScore(strategy="a", total_trades=3, wins=3, invested=30.0, pnl=3.0),
            "b": StrategyScore(strategy="b", total_trades=3, wins=3, invested=30.0, pnl=12.0),
        }
        lessons = extract_lessons(scores, [])
        assert any("b" in l for l in lessons)


class TestFormatScorecard:
    def test_no_trades(self) -> None:
        output = _format_scorecard({})
        assert "No resolved" in output

    def test_scorecard_contains_strategy_name(self) -> None:
        s = StrategyScore(
            strategy="negrisk_arb",
            total_trades=3,
            wins=3,
            losses=0,
            invested=30.0,
            pnl=10.8,
        )
        output = _format_scorecard({"negrisk_arb": s})
        assert "negrisk_arb" in output
        assert "TRADE SCORECARD" in output
