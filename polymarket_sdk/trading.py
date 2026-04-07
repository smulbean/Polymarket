"""
Trading SDK functions: place orders, cancel orders, view positions.

Trading operations mutate remote state so they deliberately bypass the
cache and never cache their responses.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .cli_wrapper import CLIWrapper
from .exceptions import OrderError, ParseError
from .models import Order, OrderResult, Position

logger = logging.getLogger(__name__)


def _make_wrapper() -> CLIWrapper:
    return CLIWrapper()


# ---------------------------------------------------------------------------
# Public SDK functions
# ---------------------------------------------------------------------------


def place_order(
    market_id: str,
    outcome: str,
    side: str,
    price: float,
    size: float,
    *,
    wrapper: Optional[CLIWrapper] = None,
) -> OrderResult:
    """
    Place a limit order on a market.

    Parameters
    ----------
    market_id:
        The market to trade on.
    outcome:
        ``"YES"`` or ``"NO"``.
    side:
        ``"buy"`` or ``"sell"``.
    price:
        Limit price between 0 and 1 (inclusive).
    size:
        Number of shares to trade.

    Returns
    -------
    OrderResult
        Contains the new order ID and confirmation status.

    Raises
    ------
    ValueError
        If *outcome*, *side*, *price*, or *size* values are invalid.
    OrderError
        If the CLI reports the order could not be placed.
    """
    _validate_order_params(outcome, side, price, size)

    w = wrapper or _make_wrapper()

    try:
        raw = w.run(
            "orders",
            "place",
            "--market", market_id,
            "--outcome", outcome.upper(),
            "--side", side.lower(),
            "--price", f"{price:.6f}",
            "--size", f"{size:.6f}",
        )
    except Exception as exc:
        raise OrderError(f"Failed to place order: {exc}") from exc

    if not isinstance(raw, dict):
        raise ParseError(f"Expected dict from orders place, got {type(raw).__name__}")

    return OrderResult.from_dict(raw)


def cancel_order(
    order_id: str,
    *,
    wrapper: Optional[CLIWrapper] = None,
) -> OrderResult:
    """
    Cancel an open order by its ID.

    Raises
    ------
    OrderError
        If the CLI reports the order could not be cancelled.
    """
    if not order_id:
        raise ValueError("order_id must not be empty")

    w = wrapper or _make_wrapper()

    try:
        raw = w.run("orders", "cancel", order_id)
    except Exception as exc:
        raise OrderError(f"Failed to cancel order {order_id}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ParseError(f"Expected dict from orders cancel, got {type(raw).__name__}")

    return OrderResult.from_dict(raw)


def get_orders(
    *,
    market_id: Optional[str] = None,
    status: Optional[str] = None,
    wrapper: Optional[CLIWrapper] = None,
) -> List[Order]:
    """
    List open or historical orders.

    Parameters
    ----------
    market_id:
        Filter by market (optional).
    status:
        Filter by order status: ``"open"``, ``"filled"``, ``"cancelled"``.

    Returns
    -------
    List[Order]
    """
    w = wrapper or _make_wrapper()
    args = ["orders", "list"]
    if market_id:
        args += ["--market", market_id]
    if status:
        args += ["--status", status]

    raw = w.run(*args)

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from orders list, got {type(raw).__name__}")

    return [Order.from_dict(item) for item in raw]


def get_positions(
    *,
    wrapper: Optional[CLIWrapper] = None,
) -> List[Position]:
    """
    List all current positions for the authenticated wallet.

    Returns
    -------
    List[Position]
    """
    w = wrapper or _make_wrapper()
    raw = w.run("positions", "list")

    if not isinstance(raw, list):
        raise ParseError(f"Expected list from positions list, got {type(raw).__name__}")

    return [Position.from_dict(item) for item in raw]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_order_params(
    outcome: str, side: str, price: float, size: float
) -> None:
    if outcome.upper() not in ("YES", "NO"):
        raise ValueError(f"outcome must be 'YES' or 'NO', got {outcome!r}")
    if side.lower() not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if not (0.0 <= price <= 1.0):
        raise ValueError(f"price must be between 0 and 1, got {price}")
    if size <= 0:
        raise ValueError(f"size must be positive, got {size}")
