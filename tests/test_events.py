"""Tests for polymarket_sdk.events."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from polymarket_sdk.cache import TTLCache
from polymarket_sdk.events import get_event, list_events, search_events
from polymarket_sdk.exceptions import MarketNotFoundError, ParseError
from polymarket_sdk.models import Event, Market


class TestListEvents:
    def test_returns_list_of_events(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [event_dict]
        result = list_events(wrapper=mock_wrapper, cache=TTLCache())
        assert len(result) == 1
        assert isinstance(result[0], Event)

    def test_event_has_nested_markets(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [event_dict]
        result = list_events(wrapper=mock_wrapper, cache=TTLCache())
        assert len(result[0].markets) == 1
        assert isinstance(result[0].markets[0], Market)

    def test_passes_category_filter(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [event_dict]
        list_events(category="politics", wrapper=mock_wrapper, cache=TTLCache())
        call_args = mock_wrapper.run.call_args[0]
        assert "--category" in call_args

    def test_raises_parse_error_on_non_list(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = "invalid"
        with pytest.raises(ParseError):
            list_events(wrapper=mock_wrapper, cache=TTLCache())


class TestGetEvent:
    def test_returns_event(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = event_dict
        result = get_event("event_crypto_2025", wrapper=mock_wrapper, cache=TTLCache())
        assert isinstance(result, Event)
        assert result.id == "event_crypto_2025"
        assert result.title == "2025 Crypto Price Predictions"

    def test_raises_not_found_on_empty_response(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = {}
        with pytest.raises(MarketNotFoundError, match="Event not found"):
            get_event("bad_id", wrapper=mock_wrapper, cache=TTLCache())

    def test_cache_hit_on_second_call(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = event_dict
        cache = TTLCache()
        get_event("event_crypto_2025", wrapper=mock_wrapper, cache=cache)
        get_event("event_crypto_2025", wrapper=mock_wrapper, cache=cache)
        assert mock_wrapper.run.call_count == 1


class TestSearchEvents:
    def test_returns_list(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [event_dict]
        result = search_events("crypto", wrapper=mock_wrapper, cache=TTLCache())
        assert len(result) == 1
        assert isinstance(result[0], Event)

    def test_passes_query_arg(
        self, mock_wrapper: MagicMock, event_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [event_dict]
        search_events("election", wrapper=mock_wrapper, cache=TTLCache())
        call_args = mock_wrapper.run.call_args[0]
        assert "--query" in call_args
        assert "election" in call_args
