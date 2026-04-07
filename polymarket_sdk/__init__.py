"""
Polymarket SDK
==============

A clean Python SDK and CLI wrapper for the Polymarket prediction markets platform.

Quickstart
----------
.. code-block:: python

    from polymarket_sdk import search_markets, get_market, get_positions

    markets = search_markets("bitcoin")
    for m in markets:
        print(m.question, m.yes_price)

    positions = get_positions()

"""
from __future__ import annotations

from .cache import TTLCache, get_default_cache
from .cli_wrapper import CLIWrapper
from .data import get_price, get_price_history
from .events import get_event, list_events, search_events
from .exceptions import (
    AuthenticationError,
    CLIError,
    CLINotFoundError,
    MarketNotFoundError,
    NetworkError,
    OrderError,
    ParseError,
    PolymarketError,
)
from .export import (
    export_markets_to_csv,
    export_markets_to_json,
    export_orders_to_csv,
    export_orders_to_json,
    export_positions_to_csv,
    export_positions_to_json,
    export_price_history_to_csv,
    export_to_csv,
    export_to_json,
)
from .markets import get_market, list_markets, search_markets
from .models import (
    Event,
    Market,
    MarketPrice,
    Order,
    OrderResult,
    Position,
    PricePoint,
)
from .session import Session
from .trading import cancel_order, get_orders, get_positions, place_order

__version__ = "0.1.0"

__all__ = [
    # SDK functions — markets
    "search_markets",
    "get_market",
    "list_markets",
    # SDK functions — events
    "list_events",
    "get_event",
    "search_events",
    # SDK functions — trading
    "place_order",
    "cancel_order",
    "get_orders",
    "get_positions",
    # SDK functions — data
    "get_price",
    "get_price_history",
    # SDK functions — export
    "export_to_json",
    "export_to_csv",
    "export_markets_to_json",
    "export_markets_to_csv",
    "export_positions_to_json",
    "export_positions_to_csv",
    "export_orders_to_json",
    "export_orders_to_csv",
    "export_price_history_to_csv",
    # Models
    "Market",
    "Event",
    "Position",
    "Order",
    "OrderResult",
    "PricePoint",
    "MarketPrice",
    # Infrastructure
    "CLIWrapper",
    "Session",
    "TTLCache",
    "get_default_cache",
    # Exceptions
    "PolymarketError",
    "CLINotFoundError",
    "CLIError",
    "ParseError",
    "MarketNotFoundError",
    "OrderError",
    "AuthenticationError",
    "NetworkError",
]
