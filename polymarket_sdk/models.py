"""
Structured data models for the Polymarket SDK.

All CLI JSON responses are parsed into these dataclasses before being
returned to callers.  No raw dicts escape the SDK boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Market:
    """A single Polymarket prediction market."""

    id: str
    question: str
    description: str
    end_date: str
    status: str                    # "active" | "resolved" | "closed"
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Market":
        return cls(
            id=data["id"],
            question=data["question"],
            description=data.get("description", ""),
            end_date=data.get("end_date", ""),
            status=data.get("status", "unknown"),
            yes_price=float(data.get("yes_price", 0.0)),
            no_price=float(data.get("no_price", 0.0)),
            volume=float(data.get("volume", 0.0)),
            liquidity=float(data.get("liquidity", 0.0)),
            category=data.get("category"),
            tags=list(data.get("tags", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "description": self.description,
            "end_date": self.end_date,
            "status": self.status,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "category": self.category,
            "tags": self.tags,
        }


@dataclass
class Event:
    """A Polymarket event grouping one or more related markets."""

    id: str
    title: str
    description: str
    category: str
    markets: List[Market] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        markets = [
            Market.from_dict(m) if isinstance(m, dict) else m
            for m in data.get("markets", [])
        ]
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", ""),
            markets=markets,
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "markets": [m.to_dict() for m in self.markets],
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass
class Position:
    """An open or closed position in a market."""

    market_id: str
    market_question: str
    outcome: str        # "YES" | "NO"
    size: float
    avg_price: float
    current_price: float
    pnl: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        return cls(
            market_id=data["market_id"],
            market_question=data.get("market_question", ""),
            outcome=data.get("outcome", "YES"),
            size=float(data.get("size", 0.0)),
            avg_price=float(data.get("avg_price", 0.0)),
            current_price=float(data.get("current_price", 0.0)),
            pnl=float(data.get("pnl", 0.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "market_question": self.market_question,
            "outcome": self.outcome,
            "size": self.size,
            "avg_price": self.avg_price,
            "current_price": self.current_price,
            "pnl": self.pnl,
        }


@dataclass
class Order:
    """A placed order (open, filled, or cancelled)."""

    id: str
    market_id: str
    outcome: str        # "YES" | "NO"
    side: str           # "buy" | "sell"
    price: float
    size: float
    filled: float
    status: str         # "open" | "filled" | "cancelled"
    created_at: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Order":
        return cls(
            id=data["id"],
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", "YES"),
            side=data.get("side", "buy"),
            price=float(data.get("price", 0.0)),
            size=float(data.get("size", 0.0)),
            filled=float(data.get("filled", 0.0)),
            status=data.get("status", "open"),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "market_id": self.market_id,
            "outcome": self.outcome,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "filled": self.filled,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class OrderResult:
    """Response object returned after placing or cancelling an order."""

    order_id: str
    status: str
    message: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderResult":
        return cls(
            order_id=data.get("order_id", ""),
            status=data.get("status", ""),
            message=data.get("message", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class PricePoint:
    """A single point in a market's price history."""

    timestamp: str
    price: float
    volume: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PricePoint":
        return cls(
            timestamp=data["timestamp"],
            price=float(data["price"]),
            volume=float(data["volume"]) if data.get("volume") is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "price": self.price,
            "volume": self.volume,
        }


@dataclass
class MarketPrice:
    """Current bid/ask prices for a market."""

    market_id: str
    yes_price: float
    no_price: float
    timestamp: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketPrice":
        return cls(
            market_id=data["market_id"],
            yes_price=float(data.get("yes_price", 0.0)),
            no_price=float(data.get("no_price", 0.0)),
            timestamp=data.get("timestamp", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "timestamp": self.timestamp,
        }
