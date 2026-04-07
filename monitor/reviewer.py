"""
Learning loop — trade reviewer and strategy scorer.

After markets resolve, the reviewer:
1. Cross-references open trades against the Polymarket data API.
2. Marks trades as won/lost and records P&L.
3. Scores each strategy (win rate, ROI).
4. Extracts human-readable lessons.
5. Persists lessons to the Claude Code memory system so they carry
   over into future conversations.

Run after each monitor cycle, or on demand:
    python -m monitor.reviewer
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .models import StrategyScore
from .storage import (
    LESSONS_FILE,
    load_lessons,
    load_trades,
    now_iso,
    save_lesson,
    update_trade,
)

logger = logging.getLogger(__name__)

# Claude Code memory directory for this project
_MEMORY_DIR = (
    Path.home()
    / ".claude"
    / "projects"
    / "-Users-graceyin-Desktop-Polymarket"
    / "memory"
)
_LESSONS_MEMORY_FILE = _MEMORY_DIR / "project_trading_lessons.md"
_MEMORY_INDEX = _MEMORY_DIR / "MEMORY.md"

# ---------------------------------------------------------------------------
# Outcome resolution
# ---------------------------------------------------------------------------


def _fetch_market_outcome(
    condition_id: str, config: Config
) -> Optional[str]:
    """
    Check whether a market has resolved and, if so, which side won.

    Returns ``"YES"``, ``"NO"``, or None (still open).
    Uses the public Gamma API — no credentials needed.
    """
    if not condition_id:
        return None
    try:
        import requests

        resp = requests.get(
            f"https://gamma-api.polymarket.com/markets",
            params={"conditionIds": condition_id},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        for m in markets:
            if not m.get("closed") and not m.get("resolved"):
                return None
            # Check outcomePrices: the resolved outcome settles to 1.0
            prices_raw = m.get("outcomePrices", '["0.5","0.5"]')
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if prices and float(prices[0]) >= 0.99:
                return "YES"
            if len(prices) > 1 and float(prices[1]) >= 0.99:
                return "NO"
    except Exception as exc:
        logger.debug("Could not check resolution for %s: %s", condition_id[:10], exc)
    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def compute_strategy_scores(
    trades: List[Dict[str, Any]],
) -> Dict[str, StrategyScore]:
    """Aggregate resolved trades into per-strategy scores."""
    scores: Dict[str, StrategyScore] = defaultdict(lambda: StrategyScore(strategy=""))
    for t in trades:
        if t.get("status") not in ("won", "lost"):
            continue
        strat = t.get("strategy", "manual")
        if strat not in scores:
            scores[strat] = StrategyScore(strategy=strat)
        s = scores[strat]
        s.total_trades += 1
        cost = float(t.get("cost", 0))
        pnl = float(t.get("pnl", 0))
        s.invested += cost
        s.pnl += pnl
        if t.get("status") == "won":
            s.wins += 1
        else:
            s.losses += 1
    return dict(scores)


def _format_scorecard(scores: Dict[str, StrategyScore]) -> str:
    resolved = [s for s in scores.values() if s.total_trades > 0]
    if not resolved:
        return "No resolved trades yet."

    total_trades = sum(s.total_trades for s in resolved)
    total_wins = sum(s.wins for s in resolved)
    total_invested = sum(s.invested for s in resolved)
    total_pnl = sum(s.pnl for s in resolved)
    overall_wr = total_wins / total_trades if total_trades else 0

    lines = [
        "TRADE SCORECARD",
        f"Overall: {total_trades} resolved | "
        f"{total_wins}W/{total_trades - total_wins}L | "
        f"{overall_wr * 100:.0f}% win rate",
        f"Invested: ${total_invested:.2f} | "
        f"Realized P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:.2f} | "
        f"ROI: {total_pnl / total_invested * 100:+.1f}%" if total_invested else "",
        "",
        f"{'Strategy':<20} {'Trades':>6} {'W/L':>9} {'Win%':>7} {'P&L':>8} {'ROI':>8}",
        "-" * 62,
    ]
    for s in sorted(resolved, key=lambda x: -x.roi):
        wl = f"{s.wins}W/{s.losses}L"
        pnl_str = f"{'+' if s.pnl >= 0 else ''}${s.pnl:.2f}"
        lines.append(
            f"{s.strategy:<20} {s.total_trades:>6} {wl:>9}"
            f" {s.win_rate * 100:>6.1f}% {pnl_str:>8} {s.roi * 100:>7.1f}%"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lesson extraction
# ---------------------------------------------------------------------------


def extract_lessons(
    scores: Dict[str, StrategyScore],
    trades: List[Dict[str, Any]],
) -> List[str]:
    """
    Generate human-readable lessons from strategy performance.

    These are opinionated heuristics — not financial advice.
    """
    lessons: List[str] = []

    for s in scores.values():
        if s.total_trades < 2:
            continue
        if s.win_rate >= 0.90 and s.total_trades >= 3:
            lessons.append(
                f"{s.strategy} is performing excellently: "
                f"{s.win_rate * 100:.0f}% win rate, {s.roi * 100:.1f}% ROI "
                f"across {s.total_trades} trades."
            )
        elif s.win_rate <= 0.40 and s.total_trades >= 3:
            lessons.append(
                f"{s.strategy} is underperforming: "
                f"{s.win_rate * 100:.0f}% win rate.  Review entry criteria."
            )
        if s.roi > 0.30:
            lessons.append(
                f"{s.strategy} generates strong ROI ({s.roi * 100:.1f}%).  "
                "Prioritise when opportunities are found."
            )

    # Best strategy
    if scores:
        best = max(scores.values(), key=lambda x: x.roi)
        if best.total_trades >= 2:
            lessons.append(
                f"Best strategy by ROI: {best.strategy} at {best.roi * 100:.1f}%.  "
                "Allocate the most capital here."
            )

    # Near-resolution pattern
    nr = scores.get("near_resolution")
    if nr and nr.total_trades >= 2 and nr.win_rate >= 0.80:
        lessons.append(
            "Near-resolution harvests are reliable.  "
            "Run the monitor within 4 hours of market close for best results."
        )

    return lessons


# ---------------------------------------------------------------------------
# Memory persistence
# ---------------------------------------------------------------------------


def _update_memory(
    scores: Dict[str, StrategyScore], lessons: List[str]
) -> None:
    """
    Write trading performance to the Claude Code persistent memory.

    Creates / overwrites the project_trading_lessons.md file and ensures
    it is listed in MEMORY.md.
    """
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scorecard = _format_scorecard(scores)

    content = f"""---
name: Trading Performance & Lessons
description: Live trading scorecard, strategy scores, and learned rules from resolved Polymarket trades
type: project
---

*Last updated: {timestamp}*

## Scorecard

```
{scorecard}
```

## Learned Rules

"""
    for lesson in lessons:
        content += f"- {lesson}\n"

    content += f"""
**Why:** These lessons are extracted from resolved trade outcomes and updated automatically by the reviewer.
**How to apply:** Use the strategy scores to prioritize which opportunities to execute. Follow the learned rules when deciding entry prices and position sizes.
"""

    _LESSONS_MEMORY_FILE.write_text(content, encoding="utf-8")

    # Update MEMORY.md index
    _update_memory_index()


def _update_memory_index() -> None:
    if not _MEMORY_INDEX.exists():
        return
    existing = _MEMORY_INDEX.read_text(encoding="utf-8")
    entry = "- [Trading Performance & Lessons](project_trading_lessons.md) — Live scorecard, strategy ROI, and extracted trading rules"
    if "project_trading_lessons.md" not in existing:
        with open(_MEMORY_INDEX, "a", encoding="utf-8") as fh:
            fh.write(f"\n{entry}\n")


# ---------------------------------------------------------------------------
# Main reviewer
# ---------------------------------------------------------------------------


class Reviewer:
    """Checks trade outcomes, scores strategies, extracts lessons."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config.load()

    def run(self, update_memory: bool = True) -> Dict[str, Any]:
        """
        Execute one review cycle.

        1. Load all trades.
        2. Check unresolved trades against the API.
        3. Mark won/lost, record P&L.
        4. Compute strategy scores.
        5. Extract and persist lessons.

        Returns
        -------
        dict
            Summary with keys: resolved_count, scores, lessons.
        """
        trades = load_trades()
        resolved_count = 0

        for trade in trades:
            if trade.get("status") not in ("open",):
                continue
            if trade.get("dry_run", True):
                continue  # Don't check dry-run trades

            condition_id = trade.get("condition_id", "")
            outcome_winner = _fetch_market_outcome(condition_id, self.config)
            if outcome_winner is None:
                continue  # Still open

            trade_outcome = trade.get("outcome", "YES")
            size = float(trade.get("size", 0))
            cost = float(trade.get("cost", 0))

            if outcome_winner == trade_outcome:
                # Won: payout = size (each winning share pays $1)
                payout = size
                pnl = payout - cost
                status = "won"
            else:
                payout = 0.0
                pnl = -cost
                status = "lost"

            updates = {
                "status": status,
                "resolved_at": now_iso(),
                "payout": round(payout, 6),
                "pnl": round(pnl, 6),
            }
            if update_trade(trade["trade_id"], updates):
                trade.update(updates)
                resolved_count += 1
                logger.info(
                    "Trade %s %s: P&L %+.2f",
                    trade["trade_id"], status.upper(), pnl,
                )

        # Re-load with updates applied
        trades = load_trades()
        scores = compute_strategy_scores(trades)
        lessons = extract_lessons(scores, trades)

        # Persist lessons to file
        for lesson in lessons:
            save_lesson(
                {
                    "lesson": lesson,
                    "source": "reviewer",
                    "resolved_count": resolved_count,
                }
            )

        if update_memory:
            _update_memory(scores, lessons)

        return {
            "resolved_count": resolved_count,
            "scores": {k: v.to_dict() for k, v in scores.items()},
            "lessons": lessons,
            "scorecard": _format_scorecard(scores),
        }


def run_reviewer(config: Optional[Config] = None) -> None:
    """Entry point for ``python -m monitor.reviewer``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    reviewer = Reviewer(config=config)
    result = reviewer.run()

    print(f"\n{result['scorecard']}")
    if result["lessons"]:
        print("\nLessons extracted:")
        for lesson in result["lessons"]:
            print(f"  • {lesson}")
    else:
        print("\nNo new lessons yet.")
    print(f"\n{result['resolved_count']} trade(s) resolved this cycle.")


if __name__ == "__main__":
    run_reviewer()
