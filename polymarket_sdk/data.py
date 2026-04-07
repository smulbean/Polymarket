"""
Price and market data SDK functions.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .cache import TTLCache, get_default_cache
from .cli_wrapper import CLIWrapper
from .exceptions import ParseError
from .models import MarketPrice, PricePoint

logger = logging.getLogger(__name__)

VALID_INTERVALS = frozenset(["1m", "5m", "15m", "1h", "4h", "1d", "1w"])


def _make_wrapper() -> CLIWrapper:
    return CLIWrapper()


# ---------------------------------------------------------------------------
# Public SDK functions
# ---------------------------------------------------------------------------


def get_price(
    market_id: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> MarketPrice:
    """
    Fetch the current YES/NO prices for a market.

    Parameters
    ----------
    market_id:
        The market to query.

    Returns
    -------
    MarketPrice
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"get_price:{market_id}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()
    raw = w.run("prices", "get", "--market", market_id)

    if not isinstance(raw, dict):
        raise ParseError(f"Expected dict from prices get, got {type(raw).__name__}")

    price = MarketPrice.from_dict(raw)

    if use_cache:
        # Prices are volatile; use a short TTL.
        _cache.set(cache_key, price, ttl=10)

    return price


def get_price_history(
    market_id: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1h",
    wrapper: Optional[CLIWrapper] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> List[PricePoint]:
    """
    Fetch historical price data for a market.

    Parameters
    ----------
    market_id:
        The market to query.
    start:
        ISO-8601 start datetime (e.g. ``"2024-01-01T00:00:00Z"``).
    end:
        ISO-8601 end datetime.
    interval:
        Candlestick interval.  Must be one of: ``1m``, ``5m``, ``15m``,
        ``1h``, ``4h``, ``1d``, ``1w``.

    Returns
    -------
    List[PricePoint]
        Data points ordered oldest-first.

    Raises
    ------
    ValueError
        If *interval* is not a recognised value.
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(
            f"interval must be one of {sorted(VALID_INTERVALS)}, got {interval!r}"
        )

    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"get_price_history:{market_id}:{start}:{end}:{interval}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()
    args = ["prices", "history", "--market", market_id, "--interval", interval]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(
            f"Expected list from prices history, got {type(raw).__name__}"
        )

    points = [PricePoint.from_dict(item) for item in raw]

    if use_cache:
        _cache.set(cache_key, points, ttl=30)

    return points
