"""Tests for polymarket_sdk.trading."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from polymarket_sdk.exceptions import OrderError, ParseError
from polymarket_sdk.models import Order, OrderResult, Position
from polymarket_sdk.trading import (
    _validate_order_params,
    cancel_order,
    get_orders,
    get_positions,
    place_order,
)


class TestPlaceOrder:
    def test_returns_order_result(
        self, mock_wrapper: MagicMock, order_result_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = order_result_dict
        result = place_order(
            "market_btc_100k", "YES", "buy", 0.45, 50.0, wrapper=mock_wrapper
        )
        assert isinstance(result, OrderResult)
        assert result.order_id == "ord_abc123"
        assert result.status == "filled"

    def test_calls_correct_cli_args(
        self, mock_wrapper: MagicMock, order_result_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = order_result_dict
        place_order(
            "market_btc_100k", "YES", "buy", 0.45, 100.0, wrapper=mock_wrapper
        )
        call_args = mock_wrapper.run.call_args[0]
        assert "orders" in call_args
        assert "place" in call_args
        assert "--market" in call_args
        assert "market_btc_100k" in call_args
        assert "--outcome" in call_args
        assert "YES" in call_args

    def test_raises_value_error_on_bad_outcome(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="outcome"):
            place_order("m1", "MAYBE", "buy", 0.5, 10.0, wrapper=mock_wrapper)

    def test_raises_value_error_on_bad_side(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="side"):
            place_order("m1", "YES", "hold", 0.5, 10.0, wrapper=mock_wrapper)

    def test_raises_value_error_on_price_out_of_range(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="price"):
            place_order("m1", "YES", "buy", 1.5, 10.0, wrapper=mock_wrapper)

    def test_raises_value_error_on_negative_size(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="size"):
            place_order("m1", "YES", "buy", 0.5, -5.0, wrapper=mock_wrapper)

    def test_wraps_cli_error_as_order_error(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.side_effect = Exception("order rejected")
        with pytest.raises(OrderError, match="Failed to place order"):
            place_order("m1", "YES", "buy", 0.5, 10.0, wrapper=mock_wrapper)


class TestCancelOrder:
    def test_cancels_successfully(
        self, mock_wrapper: MagicMock, order_result_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = {
            **order_result_dict,
            "status": "cancelled",
            "message": "Order cancelled",
        }
        result = cancel_order("ord_abc123", wrapper=mock_wrapper)
        assert isinstance(result, OrderResult)
        assert result.status == "cancelled"

    def test_raises_value_error_on_empty_id(
        self, mock_wrapper: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match="order_id"):
            cancel_order("", wrapper=mock_wrapper)

    def test_wraps_cli_error_as_order_error(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.side_effect = Exception("already cancelled")
        with pytest.raises(OrderError, match="Failed to cancel"):
            cancel_order("ord_xyz", wrapper=mock_wrapper)


class TestGetOrders:
    def test_returns_list_of_orders(
        self, mock_wrapper: MagicMock, order_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [order_dict]
        result = get_orders(wrapper=mock_wrapper)
        assert len(result) == 1
        assert isinstance(result[0], Order)

    def test_raises_parse_error_on_non_list(
        self, mock_wrapper: MagicMock
    ) -> None:
        mock_wrapper.run.return_value = {"not": "a list"}
        with pytest.raises(ParseError):
            get_orders(wrapper=mock_wrapper)


class TestGetPositions:
    def test_returns_list_of_positions(
        self, mock_wrapper: MagicMock, position_dict: Dict[str, Any]
    ) -> None:
        mock_wrapper.run.return_value = [position_dict]
        result = get_positions(wrapper=mock_wrapper)
        assert len(result) == 1
        assert isinstance(result[0], Position)
        assert result[0].outcome == "YES"
        assert result[0].pnl == 5.0

    def test_empty_positions(self, mock_wrapper: MagicMock) -> None:
        mock_wrapper.run.return_value = []
        result = get_positions(wrapper=mock_wrapper)
        assert result == []


class TestValidateOrderParams:
    @pytest.mark.parametrize("outcome", ["YES", "yes", "No", "NO"])
    def test_valid_outcomes(self, outcome: str) -> None:
        _validate_order_params(outcome, "buy", 0.5, 10.0)  # no exception

    @pytest.mark.parametrize("side", ["buy", "BUY", "sell", "SELL"])
    def test_valid_sides(self, side: str) -> None:
        _validate_order_params("YES", side, 0.5, 10.0)  # no exception

    @pytest.mark.parametrize("price", [0.0, 0.5, 1.0])
    def test_boundary_prices_valid(self, price: float) -> None:
        _validate_order_params("YES", "buy", price, 10.0)  # no exception
