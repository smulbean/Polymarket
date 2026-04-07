"""
Price monitor — the core monitoring loop.

Run once:
    python -m monitor.monitor

With the Claude Code /loop command it runs every 5 minutes automatically:
    /loop 5m python -m monitor.monitor

Output mirrors the article's format:
    ============================================================
    Polymarket Monitor — 2026-03-15 17:51:14 UTC
    ============================================================
    Watching 3 market(s)
    ...
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .backend import PolymarketBackend
from .config import Config
from .models import AlertRule, MarketSnapshot, NearResolutionOpportunity
from .opportunities import find_near_resolution_opportunities
from .storage import save_price_point, save_snapshot, now_iso
from polymarket_sdk.session import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rendering helpers (plain-text, no Rich dependency in the loop output)
# ---------------------------------------------------------------------------

SEP = "=" * 60


def _header() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"\n{SEP}\nPolymarket Monitor — {ts}\n{SEP}"


def _render_market(
    snap: MarketSnapshot,
    alerts: List[AlertRule],
    prev_price: Optional[float] = None,
) -> str:
    fired = [r for r in alerts if r.market_id == snap.market_id and r.evaluate(snap)]
    lines = [f"\n  {snap.question}"]
    pct = ""
    if prev_price is not None and prev_price > 0:
        chg = (snap.yes_price - prev_price) / prev_price * 100
        pct = f"  ({chg:+.1f}%)"
    lines.append(
        f"    Yes: {snap.yes_price * 100:.1f}c | No: {snap.no_price * 100:.1f}c"
        f" | {snap.status.upper()}{pct}"
    )
    if fired:
        for rule in fired:
            lines.append(f"    ⚠  ALERT: {rule.field} {rule.operator} {rule.threshold} {rule.note}")
    else:
        lines.append("    (no alerts)")
    return "\n".join(lines)


def _render_portfolio(positions: List[dict]) -> str:
    if not positions:
        return "\nPORTFOLIO\n  No open positions."
    lines = [f"\nPORTFOLIO ({len(positions)} position(s))"]
    for p in positions:
        question = p.get("market", {}).get("question", p.get("conditionId", ""))[:55]
        size = float(p.get("size", 0))
        avg = float(p.get("avgPrice", 0))
        cur = float(p.get("currentValue", 0))
        upnl = float(p.get("unrealizedPnl", 0))
        cost = size * avg
        pnl_sign = "+" if upnl >= 0 else ""
        pct = f"{upnl / cost * 100:+.1f}%" if cost else "n/a"
        side = "Yes" if p.get("outcome", "YES") == "YES" else "No"
        lines.append(
            f"  {question}\n"
            f"    {int(size)} {side} @ {avg * 100:.1f}c → {cur / size * 100:.1f}c"
            f" | Value: ${cur:.2f} | P&L: {pnl_sign}${upnl:.2f} ({pct})"
        )
    return "\n".join(lines)


def _render_opportunities(opps: List[NearResolutionOpportunity]) -> str:
    if not opps:
        return "\nTOP OPPORTUNITIES\n  None found."
    lines = [f"\nTOP OPPORTUNITIES"]
    for opp in opps[:5]:
        roi_pct = opp.roi * 100
        lines.append(
            f"  {opp.market.question}\n"
            f"    {opp.outcome} @ {opp.price * 100:.1f}c"
            f" | {roi_pct:.1f}% ROI | {opp.hours_to_resolution:.0f}h | {opp.confidence}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Monitor run
# ---------------------------------------------------------------------------


class Monitor:
    """
    Runs one monitoring cycle: fetch → evaluate → display → persist.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        backend: Optional[PolymarketBackend] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.config = config or Config.load()
        self.backend = backend or PolymarketBackend(self.config)
        self.session = session or Session()

    def run(self) -> None:
        """Execute one full monitoring cycle and print results."""
        print(_header())

        watchlist = self.session.watchlist
        alert_rules = self._load_alert_rules()

        # ------------------------------------------------------------------
        # Watchlist prices
        # ------------------------------------------------------------------
        snapshots: List[MarketSnapshot] = []
        if not watchlist:
            print("\n  Watchlist is empty.  Use 'polymarket-sdk watchlist add <id>' to add markets.")
        else:
            print(f"\nWatching {len(watchlist)} market(s)")
            for market_id in watchlist:
                snap = self.backend.get_market(market_id)
                if snap is None:
                    print(f"\n  [{market_id}] — could not fetch market data")
                    continue
                snapshots.append(snap)
                print(_render_market(snap, alert_rules))
                save_price_point(
                    market_id,
                    {"yes_price": snap.yes_price, "no_price": snap.no_price},
                )

        # ------------------------------------------------------------------
        # Portfolio P&L
        # ------------------------------------------------------------------
        positions: List[dict] = []
        if self.config.api.proxy_address:
            try:
                positions = self.backend.get_positions(self.config.api.proxy_address)
            except Exception as exc:
                logger.warning("Could not fetch positions: %s", exc)
        print(_render_portfolio(positions))

        # ------------------------------------------------------------------
        # Near-resolution opportunities
        # ------------------------------------------------------------------
        try:
            markets = self.backend.list_markets(limit=200)
            opps = find_near_resolution_opportunities(
                markets,
                hours_window=self.config.monitor.near_resolution_hours,
                min_confidence=self.config.monitor.near_resolution_min_confidence,
            )
            print(_render_opportunities(opps[: self.config.monitor.max_opportunities]))
        except Exception as exc:
            logger.warning("Opportunity scan failed: %s", exc)
            print("\nTOP OPPORTUNITIES\n  Scan failed — check network connection.")

        # ------------------------------------------------------------------
        # Save snapshot
        # ------------------------------------------------------------------
        save_snapshot(
            {
                "watchlist_count": len(watchlist),
                "snapshots": [s.to_dict() for s in snapshots],
                "positions_count": len(positions),
            }
        )

        print(f"\n{SEP}\n")

    def _load_alert_rules(self) -> List[AlertRule]:
        rules = []
        for raw in self.config.alerts:
            try:
                rules.append(
                    AlertRule(
                        market_id=raw["market_id"],
                        field=raw.get("field", "yes_price"),
                        operator=raw.get("operator", "above"),
                        threshold=float(raw["threshold"]),
                        note=raw.get("note", ""),
                    )
                )
            except (KeyError, ValueError):
                continue
        return rules


def run_monitor(config: Optional[Config] = None) -> None:
    """Entry point for ``python -m monitor.monitor``."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        Monitor(config=config).run()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
        sys.exit(0)


if __name__ == "__main__":
    run_monitor()
