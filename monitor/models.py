"""
Data models for the Polymarket monitor system.

These models are separate from the Phase-1 SDK models because they carry
live-data fields (last_updated, alert status, entry price tracking) that
don't belong in the read-only SDK layer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketSnapshot:
    """A timestamped price snapshot for a single market."""

    market_id: str
    question: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    end_date: str
    status: str           # "active" | "resolved" | "closed"
    neg_risk: bool = False
    neg_risk_market_id: Optional[str] = None
    group_item_title: Optional[str] = None     # candidate / outcome label
    event_id: Optional[str] = None
    timestamp: str = ""   # ISO-8601, set by storage layer

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "question": self.question,
            "condition_id": self.condition_id,
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "end_date": self.end_date,
            "status": self.status,
            "neg_risk": self.neg_risk,
            "neg_risk_market_id": self.neg_risk_market_id,
            "group_item_title": self.group_item_title,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MarketSnapshot":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class TradeRecord:
    """
    A single trade, persisted to the trade log.

    strategy values: "negrisk_arb", "near_resolution", "bracket_arb",
                     "conviction", "manual"
    """

    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = ""
    market_id: str = ""
    market_question: str = ""
    condition_id: str = ""
    token_id: str = ""           # The token being traded (YES or NO token)
    outcome: str = ""            # "YES" | "NO"
    side: str = "buy"            # "buy" | "sell"
    price: float = 0.0
    size: float = 0.0            # Number of shares
    cost: float = 0.0            # price * size
    strategy: str = "manual"
    status: str = "open"         # "open" | "won" | "lost" | "cancelled"
    order_id: str = ""           # Exchange order ID
    resolved_at: str = ""
    payout: float = 0.0
    pnl: float = 0.0
    dry_run: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp,
            "market_id": self.market_id,
            "market_question": self.market_question,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "outcome": self.outcome,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "cost": self.cost,
            "strategy": self.strategy,
            "status": self.status,
            "order_id": self.order_id,
            "resolved_at": self.resolved_at,
            "payout": self.payout,
            "pnl": self.pnl,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TradeRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class NegRiskOpportunity:
    """
    A NegRisk arbitrage opportunity.

    In a multi-outcome NegRisk market, exactly one candidate wins.
    If YES prices sum < 1.0, buying all YES shares guarantees a profit.
    If YES prices sum > 1.0, buying all NO shares guarantees a profit.
    """

    group_id: str               # neg_risk_market_id
    group_label: str            # e.g. "Vermont Governor Dem Primary"
    markets: List[MarketSnapshot]
    yes_sum: float              # Sum of all YES prices
    action: str                 # "buy_all_yes" | "buy_all_no"
    cost_per_set: float         # Total cost to buy one full set
    payout_per_set: float       # Guaranteed payout per set (always 1.0)
    profit_per_set: float       # payout - cost
    roi: float                  # profit / cost

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_label": self.group_label,
            "yes_sum": round(self.yes_sum, 4),
            "action": self.action,
            "cost_per_set": round(self.cost_per_set, 4),
            "payout_per_set": self.payout_per_set,
            "profit_per_set": round(self.profit_per_set, 4),
            "roi": round(self.roi, 4),
            "market_count": len(self.markets),
        }


@dataclass
class BracketOpportunity:
    """
    A bracket (ladder) arbitrage opportunity.

    In a ladder market (BTC > $68k, $70k, $72k), higher thresholds
    should always be priced lower or equal. Violations indicate mispricing.
    """

    event_id: str
    event_title: str
    violation_type: str          # "monotonicity" | "negative_range" | "stale_extreme"
    lower_market: MarketSnapshot
    higher_market: MarketSnapshot
    description: str
    estimated_edge: float        # approximate profit per $1 invested

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_title": self.event_title,
            "violation_type": self.violation_type,
            "lower_market_id": self.lower_market.market_id,
            "higher_market_id": self.higher_market.market_id,
            "description": self.description,
            "estimated_edge": round(self.estimated_edge, 4),
        }


@dataclass
class NearResolutionOpportunity:
    """
    A near-certainty trade on a market resolving soon.

    Qualifies when: market resolves within `hours_to_resolution` hours
    AND one outcome is priced at >= `min_confidence`.
    """

    market: MarketSnapshot
    outcome: str                 # "YES" | "NO"
    price: float                 # Entry price (e.g. 0.93)
    hours_to_resolution: float
    roi: float                   # (1.0 - price) / price
    confidence: str              # "HIGH" | "MEDIUM"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market.market_id,
            "question": self.market.question,
            "outcome": self.outcome,
            "price": round(self.price, 4),
            "hours_to_resolution": round(self.hours_to_resolution, 1),
            "roi": round(self.roi, 4),
            "confidence": self.confidence,
        }


@dataclass
class AlertRule:
    """A user-defined price alert for a watched market."""

    market_id: str
    field: str          # "yes_price" | "no_price"
    operator: str       # "above" | "below"
    threshold: float
    note: str = ""

    def evaluate(self, snapshot: MarketSnapshot) -> bool:
        value = snapshot.yes_price if self.field == "yes_price" else snapshot.no_price
        if self.operator == "above":
            return value > self.threshold
        return value < self.threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "field": self.field,
            "operator": self.operator,
            "threshold": self.threshold,
            "note": self.note,
        }


@dataclass
class StrategyScore:
    """Aggregate performance stats for a single trading strategy."""

    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    invested: float = 0.0
    pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    @property
    def roi(self) -> float:
        if self.invested == 0:
            return 0.0
        return self.pnl / self.invested

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "invested": round(self.invested, 2),
            "pnl": round(self.pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "roi": round(self.roi, 4),
        }
