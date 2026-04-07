"""
NegRisk arbitrage scanner.

In a Polymarket NegRisk multi-outcome market (e.g. "Who will win the
Vermont Governor race?"), exactly ONE candidate wins.  Each candidate has
a YES token.  The sum of all YES prices must equal exactly $1.00 because
someone always wins.

When the market is mispriced:

  sum(YES prices) < 1.00
    → Buy one YES share of EVERY candidate for total cost = sum.
    → Whoever wins, you receive $1.00.
    → Guaranteed profit = 1.00 - sum.

  sum(YES prices) > 1.00
    → Sell one YES share of every candidate (or equivalently buy all NO)
      via NegRisk mechanics.
    → Guaranteed profit = sum - 1.00.

The NegRisk rebalancing mechanism has extracted $29M from Polymarket in
a single year — it is the most capital-efficient arb on the platform.

Usage
-----
    from monitor.negrisk import NegRiskScanner, scan_negrisk_arbitrage

    scanner = NegRiskScanner()
    opps = scanner.scan(markets)
    for opp in opps:
        print(opp)
"""
from __future__ import annotations

import logging
from typing import Dict, List

from .models import MarketSnapshot, NegRiskOpportunity

logger = logging.getLogger(__name__)

# Minimum gap from 1.0 to flag as an opportunity (avoids noise from
# bid-ask spread and rounding).
_MIN_GAP = 0.02   # 2 cents per set
_MAX_EXPECTED_SUM = 1.20   # Sanity check — sums above this are data errors


class NegRiskScanner:
    """
    Groups NegRisk markets by their shared negRiskMarketID and checks
    whether the YES prices sum to approximately 1.0.
    """

    def __init__(self, min_gap: float = _MIN_GAP) -> None:
        self.min_gap = min_gap

    def scan(self, markets: List[MarketSnapshot]) -> List[NegRiskOpportunity]:
        """
        Scan a list of market snapshots for NegRisk arbitrage.

        Parameters
        ----------
        markets:
            Any mix of NegRisk and non-NegRisk markets.  Non-NegRisk
            markets are silently ignored.

        Returns
        -------
        List[NegRiskOpportunity]
            Opportunities sorted by ROI descending (best first).
        """
        groups: Dict[str, List[MarketSnapshot]] = {}
        for m in markets:
            if not m.neg_risk or not m.neg_risk_market_id:
                continue
            if m.status != "active":
                continue
            groups.setdefault(m.neg_risk_market_id, []).append(m)

        opps: List[NegRiskOpportunity] = []
        for group_id, group_markets in groups.items():
            opp = self._analyze_group(group_id, group_markets)
            if opp is not None:
                opps.append(opp)

        opps.sort(key=lambda o: -o.roi)
        return opps

    def _analyze_group(
        self,
        group_id: str,
        markets: List[MarketSnapshot],
    ) -> NegRiskOpportunity | None:
        if len(markets) < 2:
            return None

        yes_sum = sum(m.yes_price for m in markets)

        if yes_sum > _MAX_EXPECTED_SUM:
            logger.debug(
                "Group %s has suspicious YES sum %.3f — skipping", group_id, yes_sum
            )
            return None

        gap = abs(yes_sum - 1.0)
        if gap < self.min_gap:
            return None  # Within noise tolerance

        # Derive a human-readable label from the questions in this group.
        group_label = _infer_group_label(markets)

        if yes_sum < 1.0:
            # Buy all YES: pay yes_sum, receive 1.00 guaranteed.
            action = "buy_all_yes"
            cost = yes_sum
            payout = 1.0
        else:
            # Buy all NO: pay (n - yes_sum) where n = number of markets
            # because each NO costs (1 - YES price).
            no_sum = sum(1.0 - m.yes_price for m in markets)
            action = "buy_all_no"
            cost = no_sum
            payout = 1.0   # Exactly one candidate loses all others

        profit = payout - cost
        roi = profit / cost if cost > 0 else 0.0

        return NegRiskOpportunity(
            group_id=group_id,
            group_label=group_label,
            markets=markets,
            yes_sum=yes_sum,
            action=action,
            cost_per_set=cost,
            payout_per_set=payout,
            profit_per_set=profit,
            roi=roi,
        )


def _infer_group_label(markets: List[MarketSnapshot]) -> str:
    """
    Attempt to derive a group label from the market questions.

    Most NegRisk groups have questions like:
        "Will Alice win the Vermont Governor race?"
        "Will Bob win the Vermont Governor race?"
    We extract the shared suffix as the group label.
    """
    questions = [m.question.strip() for m in markets]
    if not questions:
        return "Unknown group"

    # Use groupItemTitle if available (most accurate)
    titles = [m.group_item_title for m in markets if m.group_item_title]
    if len(titles) == len(markets):
        # All markets have titles — use the question of the first one stripped
        # of its title prefix.
        first_q = questions[0]
        first_title = titles[0]
        label = first_q.replace(first_title, "").strip(" —-:|")
        return label or questions[0][:60]

    # Fallback: strip common prefix from questions
    if len(questions) >= 2:
        prefix = _common_prefix(questions)
        suffix = _common_suffix(questions)
        mid = questions[0][len(prefix): len(questions[0]) - len(suffix)]
        if suffix:
            return suffix.strip(" —-:|?")[:60]

    return questions[0][:60]


def _common_prefix(strings: List[str]) -> str:
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix


def _common_suffix(strings: List[str]) -> str:
    reversed_strs = [s[::-1] for s in strings]
    return _common_prefix(reversed_strs)[::-1]


def scan_negrisk_arbitrage(
    markets: List[MarketSnapshot],
    min_gap: float = _MIN_GAP,
) -> List[NegRiskOpportunity]:
    """
    Module-level convenience function for one-shot scanning.

    Equivalent to ``NegRiskScanner(min_gap=min_gap).scan(markets)``.
    """
    return NegRiskScanner(min_gap=min_gap).scan(markets)
