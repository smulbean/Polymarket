"""
Export SDK functions: serialize SDK objects to CSV or JSON files.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Type, Union

from .models import Event, Market, Order, Position, PricePoint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert a dataclass instance to a plain dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    raise TypeError(f"Cannot serialise object of type {type(obj).__name__}")


def export_to_json(
    items: Sequence[Any],
    path: Union[str, Path],
    *,
    indent: int = 2,
) -> Path:
    """
    Write a sequence of SDK model instances to a JSON file.

    Parameters
    ----------
    items:
        Any sequence of SDK dataclass instances.
    path:
        Destination file path.  Parent directories are created if needed.
    indent:
        JSON indentation level (default: 2).

    Returns
    -------
    Path
        The resolved output path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    data = [_to_dict(item) for item in items]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent)

    logger.info("Exported %d items to %s", len(data), out)
    return out


def export_to_csv(
    items: Sequence[Any],
    path: Union[str, Path],
) -> Path:
    """
    Write a sequence of SDK model instances to a CSV file.

    The CSV header row is derived from the keys of the first item.

    Parameters
    ----------
    items:
        Non-empty sequence of SDK dataclass instances.
    path:
        Destination file path.  Parent directories are created if needed.

    Returns
    -------
    Path
        The resolved output path.

    Raises
    ------
    ValueError
        If *items* is empty.
    """
    if not items:
        raise ValueError("Cannot export an empty sequence to CSV")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = [_to_dict(item) for item in items]
    # Flatten nested lists (e.g. Market.tags) to comma-joined strings.
    for row in rows:
        for key, val in row.items():
            if isinstance(val, list):
                row[key] = ",".join(str(v) for v in val)
            elif isinstance(val, dict):
                row[key] = json.dumps(val)

    fieldnames = list(rows[0].keys())
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Exported %d rows to %s", len(rows), out)
    return out


# ---------------------------------------------------------------------------
# Typed convenience wrappers
# ---------------------------------------------------------------------------


def export_markets_to_json(markets: List[Market], path: Union[str, Path]) -> Path:
    """Export a list of markets to JSON."""
    return export_to_json(markets, path)


def export_markets_to_csv(markets: List[Market], path: Union[str, Path]) -> Path:
    """Export a list of markets to CSV."""
    return export_to_csv(markets, path)


def export_positions_to_json(
    positions: List[Position], path: Union[str, Path]
) -> Path:
    """Export a list of positions to JSON."""
    return export_to_json(positions, path)


def export_positions_to_csv(
    positions: List[Position], path: Union[str, Path]
) -> Path:
    """Export a list of positions to CSV."""
    return export_to_csv(positions, path)


def export_orders_to_json(orders: List[Order], path: Union[str, Path]) -> Path:
    """Export a list of orders to JSON."""
    return export_to_json(orders, path)


def export_orders_to_csv(orders: List[Order], path: Union[str, Path]) -> Path:
    """Export a list of orders to CSV."""
    return export_to_csv(orders, path)


def export_price_history_to_csv(
    points: List[PricePoint], path: Union[str, Path]
) -> Path:
    """Export price history to CSV."""
    return export_to_csv(points, path)
