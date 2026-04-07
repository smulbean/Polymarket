"""Tests for polymarket_sdk.models — from_dict / to_dict round-trips."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from polymarket_sdk.models import (
    Event,
    Market,
    MarketPrice,
    Order,
    OrderResult,
    Position,
    PricePoint,
)


class TestMarket:
    def test_from_dict_full(self, market_dict: Dict[str, Any]) -> None:
        m = Market.from_dict(market_dict)
        assert m.id == "market_btc_100k"
        assert m.yes_price == 0.45
        assert m.tags == ["bitcoin", "crypto", "price"]

    def test_from_dict_missing_optional_fields(self) -> None:
        m = Market.from_dict({"id": "m1", "question": "Q?"})
        assert m.category is None
        assert m.tags == []
        assert m.volume == 0.0

    def test_to_dict_round_trip(self, market_dict: Dict[str, Any]) -> None:
        m = Market.from_dict(market_dict)
        d = m.to_dict()
        assert d["id"] == market_dict["id"]
        assert d["yes_price"] == market_dict["yes_price"]
        assert d["tags"] == market_dict["tags"]


class TestEvent:
    def test_from_dict_with_nested_markets(
        self, event_dict: Dict[str, Any]
    ) -> None:
        e = Event.from_dict(event_dict)
        assert e.id == "event_crypto_2025"
        assert len(e.markets) == 1
        assert isinstance(e.markets[0], Market)

    def test_to_dict_serialises_markets(
        self, event_dict: Dict[str, Any]
    ) -> None:
        e = Event.from_dict(event_dict)
        d = e.to_dict()
        assert isinstance(d["markets"], list)
        assert d["markets"][0]["id"] == "market_btc_100k"


class TestPosition:
    def test_from_dict(self, position_dict: Dict[str, Any]) -> None:
        p = Position.from_dict(position_dict)
        assert p.outcome == "YES"
        assert p.pnl == 5.0
        assert p.avg_price == 0.40

    def test_to_dict_round_trip(self, position_dict: Dict[str, Any]) -> None:
        p = Position.from_dict(position_dict)
        assert p.to_dict()["market_id"] == position_dict["market_id"]


class TestOrder:
    def test_from_dict(self, order_dict: Dict[str, Any]) -> None:
        o = Order.from_dict(order_dict)
        assert o.id == "ord_abc123"
        assert o.side == "buy"
        assert o.filled == 50.0

    def test_to_dict_preserves_status(self, order_dict: Dict[str, Any]) -> None:
        o = Order.from_dict(order_dict)
        assert o.to_dict()["status"] == "filled"


class TestOrderResult:
    def test_from_dict(self, order_result_dict: Dict[str, Any]) -> None:
        r = OrderResult.from_dict(order_result_dict)
        assert r.order_id == "ord_abc123"
        assert r.status == "filled"

    def test_missing_fields_use_defaults(self) -> None:
        r = OrderResult.from_dict({})
        assert r.order_id == ""
        assert r.status == ""


class TestPricePoint:
    def test_from_dict_with_volume(
        self, price_history_dicts: list
    ) -> None:
        pp = PricePoint.from_dict(price_history_dicts[0])
        assert pp.price == 0.40
        assert pp.volume == 50_000.0

    def test_from_dict_without_volume(self) -> None:
        pp = PricePoint.from_dict(
            {"timestamp": "2025-01-01T00:00:00Z", "price": 0.5}
        )
        assert pp.volume is None


class TestMarketPrice:
    def test_from_dict(self, price_dict: Dict[str, Any]) -> None:
        mp = MarketPrice.from_dict(price_dict)
        assert mp.market_id == "market_btc_100k"
        assert mp.yes_price + mp.no_price == pytest.approx(1.0)
