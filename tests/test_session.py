"""Tests for polymarket_sdk.session."""
from __future__ import annotations

from pathlib import Path

import pytest

from polymarket_sdk.session import MAX_RECENT_SEARCHES, Session, SessionState


@pytest.fixture
def session(tmp_path: Path) -> Session:
    return Session(path=tmp_path / "session.json")


class TestWatchlist:
    def test_add_to_watchlist(self, session: Session) -> None:
        result = session.add_to_watchlist("market_abc")
        assert result is True
        assert "market_abc" in session.watchlist

    def test_add_duplicate_returns_false(self, session: Session) -> None:
        session.add_to_watchlist("market_abc")
        result = session.add_to_watchlist("market_abc")
        assert result is False
        assert session.watchlist.count("market_abc") == 1

    def test_remove_from_watchlist(self, session: Session) -> None:
        session.add_to_watchlist("market_abc")
        result = session.remove_from_watchlist("market_abc")
        assert result is True
        assert "market_abc" not in session.watchlist

    def test_remove_absent_returns_false(self, session: Session) -> None:
        result = session.remove_from_watchlist("nonexistent")
        assert result is False

    def test_watchlist_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        s1 = Session(path=path)
        s1.add_to_watchlist("market_x")

        s2 = Session(path=path)
        assert "market_x" in s2.watchlist


class TestSearchHistory:
    def test_record_search(self, session: Session) -> None:
        session.record_search("bitcoin")
        assert "bitcoin" in session.recent_searches

    def test_deduplicates_and_bubbles_to_top(self, session: Session) -> None:
        session.record_search("bitcoin")
        session.record_search("ethereum")
        session.record_search("bitcoin")
        searches = session.recent_searches
        assert searches[-1] == "bitcoin"
        assert searches.count("bitcoin") == 1

    def test_caps_at_max_recent_searches(self, session: Session) -> None:
        for i in range(MAX_RECENT_SEARCHES + 5):
            session.record_search(f"query_{i}")
        assert len(session.recent_searches) == MAX_RECENT_SEARCHES

    def test_clear_search_history(self, session: Session) -> None:
        session.record_search("bitcoin")
        session.clear_search_history()
        assert session.recent_searches == []


class TestWallet:
    def test_set_and_get_wallet(self, session: Session) -> None:
        session.set_wallet("0xABCD1234")
        assert session.wallet == "0xABCD1234"

    def test_clear_wallet(self, session: Session) -> None:
        session.set_wallet("0xABCD1234")
        session.clear_wallet()
        assert session.wallet is None


class TestReset:
    def test_reset_clears_all_state(self, session: Session) -> None:
        session.add_to_watchlist("market_1")
        session.record_search("bitcoin")
        session.set_wallet("0xABC")
        session.reset()
        assert session.watchlist == []
        assert session.recent_searches == []
        assert session.wallet is None


class TestSessionStateSerialization:
    def test_round_trip(self) -> None:
        state = SessionState(
            watchlist=["m1", "m2"],
            recent_searches=["bitcoin"],
            wallet="0xDEAD",
        )
        restored = SessionState.from_dict(state.to_dict())
        assert restored.watchlist == ["m1", "m2"]
        assert restored.recent_searches == ["bitcoin"]
        assert restored.wallet == "0xDEAD"
