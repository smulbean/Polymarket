"""
Market-related SDK functions.

All functions accept an optional ``wrapper`` parameter for dependency
injection (primarily used in tests).  When omitted a fresh CLIWrapper is
created; callers that issue many requests should create one wrapper and
pass it explicitly to avoid repeated PATH lookups.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .cache import TTLCache, get_default_cache
from .cli_wrapper import CLIWrapper
from .exceptions import MarketNotFoundError, ParseError
from .models import Market

logger = logging.getLogger(__name__)


def _make_wrapper() -> CLIWrapper:
    return CLIWrapper()


# ---------------------------------------------------------------------------
# Public SDK functions
# ---------------------------------------------------------------------------


def search_markets(
    query: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
    limit: Optional[int] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> List[Market]:
    """
    Search for markets matching *query*.

    Parameters
    ----------
    query:
        Free-text search string.
    wrapper:
        CLIWrapper instance to use.  A default one is created if omitted.
    limit:
        Maximum number of results to return.
    use_cache:
        Whether to serve from / populate the TTL cache.
    cache:
        Explicit cache instance (defaults to the module-level shared cache).

    Returns
    -------
    List[Market]
        Matching markets, ordered by relevance.
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"search_markets:{query}:{limit}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for key=%s", cache_key)
            return cached

    w = wrapper or _make_wrapper()
    args = ["markets", "search", "--query", query]
    if limit is not None:
        args += ["--limit", str(limit)]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from markets search, got {type(raw).__name__}")

    markets = [Market.from_dict(item) for item in raw]

    if use_cache:
        _cache.set(cache_key, markets)

    return markets


def get_market(
    market_id: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> Market:
    """
    Fetch a single market by its ID.

    Raises
    ------
    MarketNotFoundError
        If the CLI reports the market does not exist.
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"get_market:{market_id}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()

    try:
        raw = w.run("markets", "get", market_id)
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg or "404" in msg:
            raise MarketNotFoundError(f"Market not found: {market_id}") from exc
        raise

    if not raw:
        raise MarketNotFoundError(f"Market not found: {market_id}")

    if not isinstance(raw, dict):
        raise ParseError(f"Expected dict from markets get, got {type(raw).__name__}")

    market = Market.from_dict(raw)

    if use_cache:
        _cache.set(cache_key, market)

    return market


def list_markets(
    *,
    wrapper: Optional[CLIWrapper] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> List[Market]:
    """
    List all markets, optionally filtered by status and/or category.

    Parameters
    ----------
    status:
        Filter by market status (``"active"``, ``"resolved"``, ``"closed"``).
    category:
        Filter by category slug (e.g. ``"crypto"``, ``"politics"``).
    limit:
        Maximum number of results to return.
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"list_markets:{status}:{category}:{limit}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()
    args = ["markets", "list"]
    if status:
        args += ["--status", status]
    if category:
        args += ["--category", category]
    if limit is not None:
        args += ["--limit", str(limit)]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from markets list, got {type(raw).__name__}")

    markets = [Market.from_dict(item) for item in raw]

    if use_cache:
        _cache.set(cache_key, markets)

    return markets
