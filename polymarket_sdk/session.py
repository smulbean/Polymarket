"""
Persistent session state for the Polymarket SDK.

State is stored as JSON at ``~/.polymarket/session.json`` (or a custom
path).  The session tracks the user's watchlist, recent search history,
and optional wallet context across CLI invocations.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SESSION_DIR = Path.home() / ".polymarket"
DEFAULT_SESSION_FILE = DEFAULT_SESSION_DIR / "session.json"
MAX_RECENT_SEARCHES = 20


@dataclass
class SessionState:
    """All persistent state for a single user session."""

    watchlist: List[str] = field(default_factory=list)
    recent_searches: List[str] = field(default_factory=list)
    wallet: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        return cls(
            watchlist=list(data.get("watchlist", [])),
            recent_searches=list(data.get("recent_searches", [])),
            wallet=data.get("wallet"),
        )


class Session:
    """
    Manages persistent user state stored in a local JSON file.

    Parameters
    ----------
    path:
        Path to the session JSON file.  Defaults to
        ``~/.polymarket/session.json``.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else DEFAULT_SESSION_FILE
        self._state = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> SessionState:
        if not self._path.exists():
            return SessionState()
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return SessionState.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load session from %s: %s", self._path, exc)
            return SessionState()

    def save(self) -> None:
        """Persist the current session state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._state.to_dict(), fh, indent=2)
        except OSError as exc:
            logger.error("Could not save session to %s: %s", self._path, exc)

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    def add_to_watchlist(self, market_id: str) -> bool:
        """
        Add *market_id* to the watchlist.

        Returns
        -------
        bool
            ``True`` if added, ``False`` if already present.
        """
        if market_id in self._state.watchlist:
            return False
        self._state.watchlist.append(market_id)
        self.save()
        return True

    def remove_from_watchlist(self, market_id: str) -> bool:
        """
        Remove *market_id* from the watchlist.

        Returns
        -------
        bool
            ``True`` if removed, ``False`` if not found.
        """
        try:
            self._state.watchlist.remove(market_id)
        except ValueError:
            return False
        self.save()
        return True

    @property
    def watchlist(self) -> List[str]:
        """Read-only view of the current watchlist."""
        return list(self._state.watchlist)

    # ------------------------------------------------------------------
    # Search history
    # ------------------------------------------------------------------

    def record_search(self, query: str) -> None:
        """
        Append *query* to recent searches (deduplicates and caps at limit).
        """
        searches = self._state.recent_searches
        # Remove existing occurrence so it bubbles to the top.
        try:
            searches.remove(query)
        except ValueError:
            pass
        searches.append(query)
        # Trim oldest entries beyond the cap.
        if len(searches) > MAX_RECENT_SEARCHES:
            self._state.recent_searches = searches[-MAX_RECENT_SEARCHES:]
        self.save()

    @property
    def recent_searches(self) -> List[str]:
        """Recent searches, most recent last."""
        return list(self._state.recent_searches)

    def clear_search_history(self) -> None:
        """Erase all recorded search queries."""
        self._state.recent_searches = []
        self.save()

    # ------------------------------------------------------------------
    # Wallet context
    # ------------------------------------------------------------------

    def set_wallet(self, address: str) -> None:
        """Store the active wallet address."""
        self._state.wallet = address
        self.save()

    def clear_wallet(self) -> None:
        """Remove the stored wallet address."""
        self._state.wallet = None
        self.save()

    @property
    def wallet(self) -> Optional[str]:
        """The currently active wallet address, or ``None``."""
        return self._state.wallet

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Wipe all state and save an empty session."""
        self._state = SessionState()
        self.save()

    @property
    def path(self) -> Path:
        return self._path
