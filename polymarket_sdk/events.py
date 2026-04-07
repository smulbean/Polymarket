"""
Event-related SDK functions.

Events are thematic groupings of related markets (e.g. all markets
related to a single election cycle).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .cache import TTLCache, get_default_cache
from .cli_wrapper import CLIWrapper
from .exceptions import MarketNotFoundError, ParseError
from .models import Event

logger = logging.getLogger(__name__)


def _make_wrapper() -> CLIWrapper:
    return CLIWrapper()


# ---------------------------------------------------------------------------
# Public SDK functions
# ---------------------------------------------------------------------------


def list_events(
    *,
    wrapper: Optional[CLIWrapper] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> List[Event]:
    """
    List available events, optionally filtered by category.

    Parameters
    ----------
    category:
        Filter by category slug (e.g. ``"politics"``, ``"sports"``).
    limit:
        Maximum number of results to return.

    Returns
    -------
    List[Event]
        Events ordered by recency (newest first).
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"list_events:{category}:{limit}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for key=%s", cache_key)
            return cached

    w = wrapper or _make_wrapper()
    args = ["events", "list"]
    if category:
        args += ["--category", category]
    if limit is not None:
        args += ["--limit", str(limit)]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from events list, got {type(raw).__name__}")

    events = [Event.from_dict(item) for item in raw]

    if use_cache:
        _cache.set(cache_key, events)

    return events


def get_event(
    event_id: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> Event:
    """
    Fetch a single event by its ID, including its child markets.

    Raises
    ------
    MarketNotFoundError
        If the CLI reports the event does not exist.
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"get_event:{event_id}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()

    try:
        raw = w.run("events", "get", event_id)
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg or "404" in msg:
            raise MarketNotFoundError(f"Event not found: {event_id}") from exc
        raise

    if not raw:
        raise MarketNotFoundError(f"Event not found: {event_id}")

    if not isinstance(raw, dict):
        raise ParseError(f"Expected dict from events get, got {type(raw).__name__}")

    event = Event.from_dict(raw)

    if use_cache:
        _cache.set(cache_key, event)

    return event


def search_events(
    query: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
    limit: Optional[int] = None,
    use_cache: bool = True,
    cache: Optional[TTLCache] = None,
) -> List[Event]:
    """
    Search events by a free-text query.

    Returns
    -------
    List[Event]
    """
    _cache = cache if cache is not None else get_default_cache()
    cache_key = f"search_events:{query}:{limit}"

    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    w = wrapper or _make_wrapper()
    args = ["events", "search", "--query", query]
    if limit is not None:
        args += ["--limit", str(limit)]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from events search, got {type(raw).__name__}")

    events = [Event.from_dict(item) for item in raw]

    if use_cache:
        _cache.set(cache_key, events)

    return events
