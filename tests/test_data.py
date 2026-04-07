"""Tests for polymarket_sdk.data."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from polymarket_sdk.cache import TTLCache
from polymarket_sdk.data import get_price, get_price_history
from polymarket_sdk.exceptions import ParseError
from polymarket_sdk.models import MarketPrice, PricePoint


class TestGetPrice:
    def test_returns_market_price(
        self, mock_wrapper: MagicMock, price_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = price_dict
        result = get_price("market_btc_100k", wrapper=mock_wrapper, cache=TTLCache())
        assert isinstance(result, MarketPrice)
        assert result.yes_price == 0.45
        assert result.no_price == 0.55

    def test_calls_correct_cli_args(
        self, mock_wrapper: MagicMock, price_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = price_dict
        get_price("market_btc_100k", wrapper=mock_wrapper, cache=TTLCache())
        mock_wrapper.run.assert_called_once_with(
            "prices", "get", "--market", "market_btc_100k"
        )

    def test_raises_parse_error_on_non_dict(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = [{"oops": "list"}]
        with pytest.raises(ParseError):
            get_price("m1", wrapper=mock_wrapper, cache=TTLCache())

    def test_cache_hit_on_second_call(
        self, mock_wrapper: MagicMock, price_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = price_dict
        cache = TTLCache()
        get_price("market_btc_100k", wrapper=mock_wrapper, cache=cache)
        get_price("market_btc_100k", wrapper=mock_wrapper, cache=cache)
        assert mock_wrapper.run.call_count == 1


class TestGetPriceHistory:
    def test_returns_list_of_price_points(
        self,
        mock_wrapper: MagicMock,
        price_history_dicts: List[Dict[str, Any]],
    ) -> None:
        mock_wrapper.run.return_value = price_history_dicts
        result = get_price_history(
            "market_btc_100k", wrapper=mock_wrapper, cache=TTLCache()
        )
        assert len(result) == 3
        assert all(isinstance(p, PricePoint) for p in result)

    def test_passes_interval_arg(
        self,
        mock_wrapper: MagicMock,
        price_history_dicts: List[Dict[str, Any]],
    ) -> None:
        mock_wrapper.run.return_value = price_history_dicts
        get_price_history(
            "m1", interval="1d", wrapper=mock_wrapper, cache=TTLCache()
        )
        call_args = mock_wrapper.run.call_args[0]
        assert "--interval" in call_args
        assert "1d" in call_args

    def test_raises_value_error_on_invalid_interval(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="interval"):
            get_price_history("m1", interval="2y", wrapper=mock_wrapper)

    def test_raises_parse_error_on_non_list(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = {"not": "list"}
        with pytest.raises(ParseError):
            get_price_history("m1", wrapper=mock_wrapper, cache=TTLCache())

    def test_passes_date_range_args(
        self,
        mock_wrapper: MagicMock,
        price_history_dicts: List[Dict[str, Any]],
    ) -> None:
        mock_wrapper.run.return_value = price_history_dicts
        get_price_history(
            "m1",
            start="2025-01-01T00:00:00Z",
            end="2025-01-02T00:00:00Z",
            wrapper=mock_wrapper,
            cache=TTLCache(),
        )
        call_args = mock_wrapper.run.call_args[0]
        assert "--start" in call_args
        assert "--end" in call_args
