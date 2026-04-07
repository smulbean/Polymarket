"""
Bracket (ladder) arbitrage scanner.

Polymarket often has a ladder of markets on the same underlying event,
e.g.:
    "Will BTC exceed $68,000 by March 31?"   YES @ 72c
    "Will BTC exceed $70,000 by March 31?"   YES @ 65c   ← expected: < 72c ✓
    "Will BTC exceed $72,000 by March 31?"   YES @ 71c   ← VIOLATION: > 65c

Higher thresholds must always be priced ≤ lower thresholds (it's
strictly harder to hit a higher target).  Any violation is either an
arbitrage opportunity or a stale quote.

Detection strategy
------------------
1. Group markets by event_id.
2. Within each group, extract numeric thresholds from the question text.
3. Sort by threshold.
4. Flag any adjacent pair where the higher threshold is priced higher
   than the lower one.
5. Also flag markets priced at the extreme (≥0.99 or ≤0.01) that
   haven't resolved yet.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from .models import BracketOpportunity, MarketSnapshot

logger = logging.getLogger(__name__)

# Regex to extract numbers from a question.
# Group 1: optional $ prefix (signals a price, not a year)
# Group 2: the number itself
# Group 3: optional scale suffix (k, m, b)
_NUMBER_RE = re.compile(
    r"([$])?\s*"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(k|m|b|billion|million|thousand)?\b",
    re.IGNORECASE,
)


def _extract_threshold(question: str) -> Optional[float]:
    """
    Extract the primary numeric threshold from a market question.

    Returns None if no number is found or the question is ambiguous.
    Numbers prefixed with ``$`` or containing commas are always treated
    as prices.  Plain integers in the range 2010–2099 are treated as
    years and ignored.
    """
    matches = _NUMBER_RE.findall(question)
    if not matches:
        return None

    values = []
    for dollar_sign, num_str, suffix in matches:
        try:
            has_dollar = bool(dollar_sign)
            has_comma = "," in num_str
            v = float(num_str.replace(",", ""))
            suffix = suffix.lower()
            if suffix in ("k", "thousand"):
                v *= 1_000
            elif suffix in ("m", "million"):
                v *= 1_000_000
            elif suffix in ("b", "billion"):
                v *= 1_000_000_000

            # Skip year-like bare integers (2010–2099) unless they have a
            # $ prefix or a comma (meaning they're definitely prices).
            if not has_dollar and not has_comma and 2010 <= v <= 2099:
                continue
            if v >= 10:
                values.append(v)
        except ValueError:
            continue

    return max(values) if values else None


def _group_by_event(markets: List[MarketSnapshot]) -> Dict[str, List[MarketSnapshot]]:
    groups: Dict[str, List[MarketSnapshot]] = {}
    for m in markets:
        if m.event_id:
            groups.setdefault(m.event_id, []).append(m)
    return groups


def scan_bracket_arbitrage(
    markets: List[MarketSnapshot],
    min_group_size: int = 2,
) -> List[BracketOpportunity]:
    """
    Scan a list of market snapshots for bracket arbitrage violations.

    Parameters
    ----------
    markets:
        All active market snapshots to consider.
    min_group_size:
        Minimum markets in a group to bother analyzing.

    Returns
    -------
    List[BracketOpportunity]
        All detected violations, sorted by estimated edge descending.
    """
    opps: List[BracketOpportunity] = []
    groups = _group_by_event(markets)

    for event_id, group in groups.items():
        if len(group) < min_group_size:
            continue

        # Assign thresholds and filter to markets that have them.
        ladder: List[Tuple[float, MarketSnapshot]] = []
        for m in group:
            t = _extract_threshold(m.question)
            if t is not None:
                ladder.append((t, m))

        if len(ladder) < min_group_size:
            continue

        ladder.sort(key=lambda x: x[0])
        event_title = group[0].question.split("?")[0][:60]

        # Check monotonicity: higher threshold → lower or equal YES price.
        for i in range(len(ladder) - 1):
            low_thresh, low_market = ladder[i]
            high_thresh, high_market = ladder[i + 1]

            if high_market.yes_price > low_market.yes_price + 0.005:
                # Violation: higher target priced higher than lower target
                edge = high_market.yes_price - low_market.yes_price
                opps.append(
                    BracketOpportunity(
                        event_id=event_id,
                        event_title=event_title,
                        violation_type="monotonicity",
                        lower_market=low_market,
                        higher_market=high_market,
                        description=(
                            f"Higher target ({high_thresh:,.0f}) priced at"
                            f" {high_market.yes_price:.3f}, above lower target"
                            f" ({low_thresh:,.0f}) at {low_market.yes_price:.3f}"
                        ),
                        estimated_edge=edge,
                    )
                )

            # Negative implied range: the price of "between L and H" is negative.
            implied_range = low_market.yes_price - high_market.yes_price
            if implied_range < -0.01:
                opps.append(
                    BracketOpportunity(
                        event_id=event_id,
                        event_title=event_title,
                        violation_type="negative_range",
                        lower_market=low_market,
                        higher_market=high_market,
                        description=(
                            f"Implied probability of range "
                            f"[{low_thresh:,.0f}, {high_thresh:,.0f}] "
                            f"is negative: {implied_range:.3f}"
                        ),
                        estimated_edge=abs(implied_range),
                    )
                )

        # Stale extremes: market at 99c+ or 1c- that hasn't resolved.
        for _thresh, m in ladder:
            if m.yes_price >= 0.99 and m.status == "active":
                opps.append(
                    BracketOpportunity(
                        event_id=event_id,
                        event_title=event_title,
                        violation_type="stale_extreme",
                        lower_market=m,
                        higher_market=m,
                        description=(
                            f"Market at {m.yes_price:.3f} (near 1.0) but not resolved"
                        ),
                        estimated_edge=0.01,
                    )
                )
            elif m.yes_price <= 0.01 and m.status == "active":
                opps.append(
                    BracketOpportunity(
                        event_id=event_id,
                        event_title=event_title,
                        violation_type="stale_extreme",
                        lower_market=m,
                        higher_market=m,
                        description=(
                            f"Market at {m.yes_price:.3f} (near 0) but not resolved"
                        ),
                        estimated_edge=0.01,
                    )
                )

    opps.sort(key=lambda o: -o.estimated_edge)
    return opps
