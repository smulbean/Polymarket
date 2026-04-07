"""
Near-resolution opportunity finder.

Scans active markets for outcomes that are near-certain (price ≥ threshold)
and resolve within a configurable time window.  These trades carry minimal
risk: you're essentially harvesting the time-value premium on a market
that's 90–99% priced in.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from .models import MarketSnapshot, NearResolutionOpportunity

logger = logging.getLogger(__name__)


def _hours_until(end_date: str) -> Optional[float]:
    """Return hours until *end_date* (ISO-8601), or None if unparseable."""
    if not end_date:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%d",
    ):
        try:
            end = datetime.strptime(end_date[:len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
            delta = (end - datetime.now(timezone.utc)).total_seconds() / 3600
            return delta
        except ValueError:
            continue
    return None


def find_near_resolution_opportunities(
    markets: List[MarketSnapshot],
    hours_window: float = 24.0,
    min_confidence: float = 0.90,
    min_roi: float = 0.01,
) -> List[NearResolutionOpportunity]:
    """
    Find markets resolving within *hours_window* with a near-certain outcome.

    Parameters
    ----------
    markets:
        Full list of active market snapshots to scan.
    hours_window:
        Include markets resolving within this many hours.
    min_confidence:
        Minimum price for the leading outcome to qualify (e.g. 0.90 = 90c).
    min_roi:
        Minimum return on investment to include (filters out 99c markets
        with only 1% ROI when you already expect low returns).

    Returns
    -------
    List[NearResolutionOpportunity]
        Sorted best-ROI first.
    """
    opps: List[NearResolutionOpportunity] = []

    for market in markets:
        if market.status != "active":
            continue

        hours = _hours_until(market.end_date)
        if hours is None or hours <= 0 or hours > hours_window:
            continue

        # Check both YES and NO for a near-certain outcome.
        for outcome, price in (("YES", market.yes_price), ("NO", market.no_price)):
            if price < min_confidence:
                continue
            roi = (1.0 - price) / price
            if roi < min_roi:
                continue
            confidence = "HIGH" if price >= 0.95 else "MEDIUM"
            opps.append(
                NearResolutionOpportunity(
                    market=market,
                    outcome=outcome,
                    price=price,
                    hours_to_resolution=hours,
                    roi=roi,
                    confidence=confidence,
                )
            )

    # Sort: HIGH confidence first, then by ROI descending.
    opps.sort(key=lambda o: (0 if o.confidence == "HIGH" else 1, -o.roi))
    return opps
