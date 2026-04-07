"""Tests for polymarket_sdk.markets."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from polymarket_sdk.cache import TTLCache
from polymarket_sdk.exceptions import MarketNotFoundError, ParseError
from polymarket_sdk.markets import get_market, list_markets, search_markets
from polymarket_sdk.models import Market


class TestSearchMarkets:
    def test_returns_list_of_markets(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [market_dict]
        cache = TTLCache()
        result = search_markets("bitcoin", wrapper=mock_wrapper, cache=cache)
        assert len(result) == 1
        assert isinstance(result[0], Market)
        assert result[0].id == "market_btc_100k"

    def test_calls_correct_cli_args(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [market_dict]
        cache = TTLCache()
        search_markets("bitcoin", wrapper=mock_wrapper, cache=cache)
        mock_wrapper.run.assert_called_once_with(
            "markets", "search", "--query", "bitcoin"
        )

    def test_passes_limit_arg(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [market_dict]
        cache = TTLCache()
        search_markets("bitcoin", limit=5, wrapper=mock_wrapper, cache=cache)
        call_args = mock_wrapper.run.call_args[0]
        assert "--limit" in call_args
        assert "5" in call_args

    def test_raises_parse_error_on_non_list(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = {"not": "a list"}
        with pytest.raises(ParseError):
            search_markets("bitcoin", wrapper=mock_wrapper, cache=TTLCache())

    def test_cache_hit_skips_wrapper(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        cache = TTLCache()
        markets = [Market.from_dict(market_dict)]
        cache.set("search_markets:bitcoin:None", markets)
        result = search_markets("bitcoin", wrapper=mock_wrapper, cache=cache)
        mock_wrapper.run.assert_not_called()
        assert result == markets

    def test_empty_result_returns_empty_list(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = []
        result = search_markets("zzznomatch", wrapper=mock_wrapper, cache=TTLCache())
        assert result == []


class TestGetMarket:
    def test_returns_single_market(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = market_dict
        cache = TTLCache()
        result = get_market("market_btc_100k", wrapper=mock_wrapper, cache=cache)
        assert isinstance(result, Market)
        assert result.id == "market_btc_100k"
        assert result.yes_price == 0.45

    def test_raises_market_not_found_on_empty_response(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = {}
        with pytest.raises(MarketNotFoundError):
            get_market("nonexistent", wrapper=mock_wrapper, cache=TTLCache())

    def test_raises_market_not_found_on_not_found_exception(
        self, mock_wrapper: MagicMock
    ) -> None:
        from polymarket_sdk.exceptions import CLIError

        mock_wrapper.run.side_effect = CLIError("market not found", returncode=404)
        with pytest.raises(MarketNotFoundError):
            get_market("nonexistent", wrapper=mock_wrapper, cache=TTLCache())

    def test_cache_populated_on_first_call(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = market_dict
        cache = TTLCache()
        get_market("market_btc_100k", wrapper=mock_wrapper, cache=cache)
        # Second call should use cache
        get_market("market_btc_100k", wrapper=mock_wrapper, cache=cache)
        assert mock_wrapper.run.call_count == 1


class TestListMarkets:
    def test_returns_multiple_markets(
        self,
        mock_wrapper: MagicMock,
        market_dict: Dict[str, Any],
        market_dict_2: Dict[str, Any],
    ) -> None:
        mock_wrapper.run.return_value = [market_dict, market_dict_2]
        result = list_markets(wrapper=mock_wrapper, cache=TTLCache())
        assert len(result) == 2
        assert all(isinstance(m, Market) for m in result)

    def test_passes_status_filter(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [market_dict]
        list_markets(status="active", wrapper=mock_wrapper, cache=TTLCache())
        call_args = mock_wrapper.run.call_args[0]
        assert "--status" in call_args
        assert "active" in call_args

    def test_passes_category_filter(
        self, mock_wrapper: MagicMock, market_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [market_dict]
        list_markets(category="crypto", wrapper=mock_wrapper, cache=TTLCache())
        call_args = mock_wrapper.run.call_args[0]
        assert "--category" in call_args
        assert "crypto" in call_args
