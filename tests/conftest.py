"""
Shared pytest fixtures for the Polymarket SDK test suite.

Tests NEVER call subprocess.run directly.  All CLIWrapper usage is either:
  1. Replaced with a MagicMock via the ``mock_wrapper`` fixture, or
  2. Patched at the subprocess.run level via pytest-mock.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from polymarket_sdk.cli_wrapper import CLIWrapper
from polymarket_sdk.models import (
    Event,
    Market,
    MarketPrice,
    Order,
    OrderResult,
    Position,
    PricePoint,
)


# ---------------------------------------------------------------------------
# Raw dict fixtures — the JSON the CLI would return
# ---------------------------------------------------------------------------


@pytest.fixture
def market_dict() -> Dict[str, Any]:
    return {
        "id": "market_btc_100k",
        "question": "Will Bitcoin reach $100k by end of 2025?",
        "description": "Resolves YES if BTC/USD closes above $100,000 on any major exchange.",
        "end_date": "2025-12-31T00:00:00Z",
        "status": "active",
        "yes_price": 0.45,
        "no_price": 0.55,
        "volume": 1_500_000.0,
        "liquidity": 250_000.0,
        "category": "crypto",
        "tags": ["bitcoin", "crypto", "price"],
    }


@pytest.fixture
def market_dict_2() -> Dict[str, Any]:
    return {
        "id": "market_eth_flip",
        "question": "Will Ethereum flippening happen before 2026?",
        "description": "Resolves YES if ETH market cap exceeds BTC market cap.",
        "end_date": "2025-12-31T00:00:00Z",
        "status": "active",
        "yes_price": 0.10,
        "no_price": 0.90,
        "volume": 500_000.0,
        "liquidity": 80_000.0,
        "category": "crypto",
        "tags": ["ethereum", "flippening"],
    }


@pytest.fixture
def event_dict(market_dict: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": "event_crypto_2025",
        "title": "2025 Crypto Price Predictions",
        "description": "Markets predicting cryptocurrency prices in 2025.",
        "category": "crypto",
        "markets": [market_dict],
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-12-31T23:59:59Z",
    }


@pytest.fixture
def position_dict() -> Dict[str, Any]:
    return {
        "market_id": "market_btc_100k",
        "market_question": "Will Bitcoin reach $100k by end of 2025?",
        "outcome": "YES",
        "size": 100.0,
        "avg_price": 0.40,
        "current_price": 0.45,
        "pnl": 5.0,
    }


@pytest.fixture
def order_dict() -> Dict[str, Any]:
    return {
        "id": "ord_abc123",
        "market_id": "market_btc_100k",
        "outcome": "YES",
        "side": "buy",
        "price": 0.45,
        "size": 50.0,
        "filled": 50.0,
        "status": "filled",
        "created_at": "2025-01-01T10:00:00Z",
    }


@pytest.fixture
def order_result_dict() -> Dict[str, Any]:
    return {
        "order_id": "ord_abc123",
        "status": "filled",
        "message": "Order placed successfully",
    }


@pytest.fixture
def price_dict() -> Dict[str, Any]:
    return {
        "market_id": "market_btc_100k",
        "yes_price": 0.45,
        "no_price": 0.55,
        "timestamp": "2025-01-01T12:00:00Z",
    }


@pytest.fixture
def price_history_dicts() -> List[Dict[str, Any]]:
    return [
        {"timestamp": "2025-01-01T00:00:00Z", "price": 0.40, "volume": 50_000.0},
        {"timestamp": "2025-01-01T01:00:00Z", "price": 0.42, "volume": 55_000.0},
        {"timestamp": "2025-01-01T02:00:00Z", "price": 0.44, "volume": 60_000.0},
    ]


# ---------------------------------------------------------------------------
# Model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_market(market_dict: Dict[str, Any]) -> Market:
    return Market.from_dict(market_dict)


@pytest.fixture
def sample_market_2(market_dict_2: Dict[str, Any]) -> Market:
    return Market.from_dict(market_dict_2)


@pytest.fixture
def sample_event(event_dict: Dict[str, Any]) -> Event:
    return Event.from_dict(event_dict)


@pytest.fixture
def sample_position(position_dict: Dict[str, Any]) -> Position:
    return Position.from_dict(position_dict)


@pytest.fixture
def sample_order(order_dict: Dict[str, Any]) -> Order:
    return Order.from_dict(order_dict)


@pytest.fixture
def sample_order_result(order_result_dict: Dict[str, Any]) -> OrderResult:
    return OrderResult.from_dict(order_result_dict)


@pytest.fixture
def sample_price(price_dict: Dict[str, Any]) -> MarketPrice:
    return MarketPrice.from_dict(price_dict)


@pytest.fixture
def sample_price_history(price_history_dicts: List[Dict[str, Any]]) -> List[PricePoint]:
    return [PricePoint.from_dict(d) for d in price_history_dicts]


# ---------------------------------------------------------------------------
# Mock wrapper
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_wrapper() -> MagicMock:
    """
    A MagicMock that satisfies CLIWrapper's interface.

    Set mock_wrapper.run.return_value to control what each SDK call returns.
    """
    wrapper = MagicMock(spec=CLIWrapper)
    return wrapper


# ---------------------------------------------------------------------------
# Temp directory
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path
