"""
Polymarket automated trading monitor.

Phases 3–7 of the automated trading system:
  - monitor.monitor      — Price monitoring loop (Phase 3)
  - monitor.scanner      — Bracket arbitrage scanner (Phase 4)
  - monitor.negrisk      — NegRisk multi-outcome scanner (Phase 4)
  - monitor.opportunities — Near-resolution finder (Phase 4)
  - monitor.executor     — Trade executor with guardrails (Phase 6)
  - monitor.reviewer     — Learning loop + strategy scorer (Phase 7)
"""
from .config import Config
from .models import (
    AlertRule,
    BracketOpportunity,
    MarketSnapshot,
    NearResolutionOpportunity,
    NegRiskOpportunity,
    StrategyScore,
    TradeRecord,
)
from .negrisk import NegRiskScanner, scan_negrisk_arbitrage
from .opportunities import find_near_resolution_opportunities
from .scanner import scan_bracket_arbitrage

__all__ = [
    "Config",
    "MarketSnapshot",
    "TradeRecord",
    "NegRiskOpportunity",
    "BracketOpportunity",
    "NearResolutionOpportunity",
    "AlertRule",
    "StrategyScore",
    "NegRiskScanner",
    "scan_negrisk_arbitrage",
    "scan_bracket_arbitrage",
    "find_near_resolution_opportunities",
]
