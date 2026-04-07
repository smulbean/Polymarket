"""
Simple TTL-based in-process cache.

Avoids redundant CLI calls for frequently repeated queries (e.g. the
same market looked up multiple times in a REPL session).  The cache is
intentionally lightweight: it lives in memory only and is not shared
across processes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Tuple


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    """
    Thread-unsafe, in-memory key/value store with per-entry TTLs.

    Parameters
    ----------
    default_ttl:
        Default time-to-live in seconds for new entries.
    """

    def __init__(self, default_ttl: int = 60) -> None:
        self.default_ttl = default_ttl
        self._store: Dict[str, _Entry] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or ``None`` if expired/absent."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store *value* under *key* with an optional custom TTL."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        self._store[key] = _Entry(
            value=value,
            expires_at=time.monotonic() + effective_ttl,
        )

    def invalidate(self, key: str) -> None:
        """Remove a single entry (no-op if absent)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Evict all entries."""
        self._store.clear()

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        return self.get(key) is not None  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, e in self._store.items() if now >= e.expires_at]
        for k in expired:
            del self._store[k]

    def stats(self) -> Dict[str, int]:
        """Return a snapshot of cache statistics."""
        self._purge_expired()
        return {"size": len(self._store), "default_ttl": self.default_ttl}


# Module-level shared cache instance used by SDK functions.
_default_cache = TTLCache(default_ttl=60)


def get_default_cache() -> TTLCache:
    """Return the module-level shared cache instance."""
    return _default_cache
