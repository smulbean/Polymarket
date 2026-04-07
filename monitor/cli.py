"""
Monitor CLI commands, integrated into the root ``polymarket-sdk`` group.

Commands
--------
  polymarket-sdk monitor run          # one monitoring cycle
  polymarket-sdk monitor scan         # bracket arbitrage scan
  polymarket-sdk monitor negrisk      # NegRisk arb scan
  polymarket-sdk monitor opportunities # near-resolution opportunities
  polymarket-sdk monitor review       # learning loop / scorecard
  polymarket-sdk monitor trades       # show trade log
  polymarket-sdk monitor config       # show / edit config
"""
from __future__ import annotations

import json
import sys
from typing import Optional

import click

from .config import Config
from .executor import (
    DailyLimitError,
    Executor,
    GuardrailError,
    PerTradeLimitError,
)
from .monitor import Monitor
from .negrisk import scan_negrisk_arbitrage
from .opportunities import find_near_resolution_opportunities
from .reviewer import Reviewer
from .scanner import scan_bracket_arbitrage
from .storage import load_trades

try:
    from rich.console import Console
    from rich.table import Table

    _console = Console()
    _RICH = True
except ImportError:
    _RICH = False


def _err(msg: str) -> None:
    click.echo(f"Error: {msg}", err=True)


# ---------------------------------------------------------------------------
# Root monitor group
# ---------------------------------------------------------------------------


@click.group("monitor")
def monitor_group() -> None:
    """Automated trading monitor, scanners, and learning loop."""


# ---------------------------------------------------------------------------
# monitor run
# ---------------------------------------------------------------------------


@monitor_group.command("run")
@click.option("--wallet", default=None, help="Override wallet address for position fetch.")
def monitor_run(wallet: Optional[str]) -> None:
    """Run one monitoring cycle (watchlist prices, P&L, opportunities)."""
    cfg = Config.load()
    if wallet:
        cfg.api.proxy_address = wallet
    Monitor(config=cfg).run()


# ---------------------------------------------------------------------------
# monitor scan (bracket arbitrage)
# ---------------------------------------------------------------------------


@monitor_group.command("scan")
@click.option("--limit", default=300, show_default=True, help="Markets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def monitor_scan(limit: int, as_json: bool) -> None:
    """Scan for bracket (ladder) arbitrage violations."""
    from .backend import PolymarketBackend

    cfg = Config.load()
    backend = PolymarketBackend(cfg)

    click.echo("Fetching markets…", err=True)
    try:
        markets = backend.list_markets(limit=limit)
    except Exception as exc:
        _err(f"Could not fetch markets: {exc}")
        sys.exit(1)

    opps = scan_bracket_arbitrage(markets)

    if as_json:
        click.echo(json.dumps([o.to_dict() for o in opps], indent=2))
        return

    if not opps:
        click.echo("No bracket arbitrage opportunities found.")
        return

    click.echo(f"\nFound {len(opps)} bracket arbitrage violation(s):\n")
    for opp in opps:
        click.echo(
            f"  [{opp.violation_type.upper()}] {opp.event_title}\n"
            f"    {opp.description}\n"
            f"    Estimated edge: {opp.estimated_edge:.3f}\n"
        )


# ---------------------------------------------------------------------------
# monitor negrisk
# ---------------------------------------------------------------------------


@monitor_group.command("negrisk")
@click.option("--limit", default=500, show_default=True, help="NegRisk markets to fetch.")
@click.option("--min-gap", default=0.02, show_default=True,
              help="Minimum gap from 1.0 to flag (e.g. 0.02 = 2c per set).")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.option("--execute", is_flag=True, help="Execute top opportunity (respects dry_run).")
@click.option("--sets", default=1, show_default=True, help="Sets to buy per arb.")
def monitor_negrisk(
    limit: int, min_gap: float, as_json: bool, execute: bool, sets: int
) -> None:
    """Scan NegRisk multi-outcome markets for YES-sum arbitrage."""
    from .backend import PolymarketBackend

    cfg = Config.load()
    backend = PolymarketBackend(cfg)

    click.echo("Fetching NegRisk markets…", err=True)
    try:
        markets = backend.list_neg_risk_markets(limit=limit)
    except Exception as exc:
        _err(f"Could not fetch markets: {exc}")
        sys.exit(1)

    opps = scan_negrisk_arbitrage(markets, min_gap=min_gap)

    if as_json:
        click.echo(json.dumps([o.to_dict() for o in opps], indent=2))
        return

    if not opps:
        click.echo("No NegRisk arbitrage opportunities found.")
        return

    click.echo(f"\nFound {len(opps)} NegRisk opportunity(-ies):\n")
    for opp in opps:
        action_str = "Buy ALL YES" if opp.action == "buy_all_yes" else "Buy ALL NO"
        click.echo(
            f"  {opp.group_label}\n"
            f"    {len(opp.markets)} priced outcomes, YES sum = {opp.yes_sum:.3f}\n"
            f"    {action_str} for ${opp.cost_per_set:.3f}/set"
            f" → guaranteed $1.00 payout\n"
            f"    Profit: ${opp.profit_per_set:.3f}/set ({opp.roi * 100:.1f}% ROI)\n"
        )

    if execute and opps:
        top = opps[0]
        dry = cfg.trading.dry_run
        mode = "DRY RUN" if dry else "LIVE"
        click.echo(f"\nExecuting top opportunity [{mode}]: {top.group_label}")

        try:
            executor = Executor(config=cfg, backend=backend)
            records = executor.execute_negrisk_arb(top.markets, sets=sets)
            click.echo(f"Placed {len(records)} order(s).")
            for r in records:
                dry_tag = " [DRY RUN]" if r.dry_run else ""
                click.echo(f"  {r.trade_id}{dry_tag}: {r.outcome} {r.market_question[:40]}"
                           f" @ {r.price:.3f} × {r.size:.0f} = ${r.cost:.2f}")
        except GuardrailError as exc:
            _err(f"Guardrail blocked trade: {exc}")


# ---------------------------------------------------------------------------
# monitor opportunities
# ---------------------------------------------------------------------------


@monitor_group.command("opportunities")
@click.option("--hours", default=24, show_default=True,
              help="Resolution window in hours.")
@click.option("--confidence", default=0.90, show_default=True,
              help="Minimum price for the leading outcome.")
@click.option("--limit", default=200, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def monitor_opportunities(hours: float, confidence: float, limit: int, as_json: bool) -> None:
    """Find near-resolution high-confidence opportunities."""
    from .backend import PolymarketBackend

    cfg = Config.load()
    backend = PolymarketBackend(cfg)

    click.echo("Fetching active markets…", err=True)
    try:
        markets = backend.list_markets(limit=limit)
    except Exception as exc:
        _err(f"Could not fetch markets: {exc}")
        sys.exit(1)

    opps = find_near_resolution_opportunities(
        markets, hours_window=hours, min_confidence=confidence
    )

    if as_json:
        click.echo(json.dumps([o.to_dict() for o in opps], indent=2))
        return

    if not opps:
        click.echo(f"No opportunities found resolving within {hours}h.")
        return

    click.echo(f"\nTop {len(opps)} near-resolution opportunities:\n")
    for opp in opps[:10]:
        click.echo(
            f"  {opp.market.question}\n"
            f"    {opp.outcome} @ {opp.price * 100:.1f}c"
            f" | {opp.roi * 100:.1f}% ROI"
            f" | {opp.hours_to_resolution:.1f}h | {opp.confidence}\n"
        )


# ---------------------------------------------------------------------------
# monitor review
# ---------------------------------------------------------------------------


@monitor_group.command("review")
@click.option("--no-memory", is_flag=True, help="Skip updating Claude Code memory.")
def monitor_review(no_memory: bool) -> None:
    """Run the learning loop: check resolutions, score strategies, extract lessons."""
    cfg = Config.load()
    reviewer = Reviewer(config=cfg)
    result = reviewer.run(update_memory=not no_memory)

    click.echo(f"\n{result['scorecard']}\n")

    if result["lessons"]:
        click.echo("Extracted lessons:")
        for lesson in result["lessons"]:
            click.echo(f"  • {lesson}")

    click.echo(f"\n{result['resolved_count']} trade(s) resolved this cycle.")
    if not no_memory:
        click.echo("Memory updated: ~/.claude/.../memory/project_trading_lessons.md")


# ---------------------------------------------------------------------------
# monitor trades
# ---------------------------------------------------------------------------


@monitor_group.command("trades")
@click.option("--status", default=None,
              type=click.Choice(["open", "won", "lost", "failed", "all"]),
              help="Filter by status.")
@click.option("--strategy", default=None, help="Filter by strategy tag.")
@click.option("--live-only", is_flag=True, help="Exclude dry-run trades.")
@click.option("--json", "as_json", is_flag=True)
def monitor_trades(
    status: Optional[str],
    strategy: Optional[str],
    live_only: bool,
    as_json: bool,
) -> None:
    """Show the trade log."""
    trades = load_trades()

    if status and status != "all":
        trades = [t for t in trades if t.get("status") == status]
    if strategy:
        trades = [t for t in trades if t.get("strategy") == strategy]
    if live_only:
        trades = [t for t in trades if not t.get("dry_run", True)]

    if as_json:
        click.echo(json.dumps(trades, indent=2))
        return

    if not trades:
        click.echo("No trades found.")
        return

    click.echo(f"\n  {len(trades)} trade(s):\n")
    for t in trades:
        dry_tag = " [DRY]" if t.get("dry_run") else ""
        pnl = t.get("pnl")
        pnl_str = f" P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}" if pnl is not None else ""
        click.echo(
            f"  [{t.get('trade_id', '?')}]{dry_tag}"
            f" {t.get('outcome','?')} {t.get('market_question','')[:45]}\n"
            f"    strategy={t.get('strategy','?')}"
            f" status={t.get('status','?')}"
            f" cost=${t.get('cost', 0):.2f}"
            f"{pnl_str}"
        )


# ---------------------------------------------------------------------------
# monitor config
# ---------------------------------------------------------------------------


@monitor_group.command("config")
@click.option("--show", is_flag=True, default=True, help="Print current config.")
@click.option("--dry-run/--live", default=None, help="Toggle dry_run mode.")
@click.option("--max-per-trade", type=float, default=None)
@click.option("--max-per-day", type=float, default=None)
@click.option("--wallet", default=None, help="Set proxy wallet address.")
def monitor_config(
    show: bool,
    dry_run: Optional[bool],
    max_per_trade: Optional[float],
    max_per_day: Optional[float],
    wallet: Optional[str],
) -> None:
    """Show or update monitor configuration."""
    cfg = Config.load()

    mutated = False
    if dry_run is not None:
        cfg.trading.dry_run = dry_run
        mutated = True
    if max_per_trade is not None:
        cfg.trading.max_per_trade = max_per_trade
        mutated = True
    if max_per_day is not None:
        cfg.trading.max_per_day = max_per_day
        mutated = True
    if wallet is not None:
        cfg.api.proxy_address = wallet
        mutated = True

    if mutated:
        cfg.save_non_sensitive()
        click.echo("Config saved.")

    click.echo(
        f"\n  dry_run          : {cfg.trading.dry_run}\n"
        f"  max_per_trade    : ${cfg.trading.max_per_trade:.2f}\n"
        f"  max_per_day      : ${cfg.trading.max_per_day:.2f}\n"
        f"  min_shares       : {cfg.trading.min_shares}\n"
        f"  proxy_address    : {cfg.api.proxy_address or '(not set)'}\n"
        f"  credentials_ok   : {cfg.has_trading_credentials}\n"
        f"  near_res_hours   : {cfg.monitor.near_resolution_hours}\n"
        f"  near_res_conf    : {cfg.monitor.near_resolution_min_confidence}\n"
        f"  claude_analyst   : {'configured' if cfg.has_claude_analyst else '(not set)'}\n"
        f"  telegram         : {'configured' if cfg.has_telegram else '(not set)'}\n"
    )


# ---------------------------------------------------------------------------
# monitor agent (background daemon)
# ---------------------------------------------------------------------------


@monitor_group.group("agent")
def agent_group() -> None:
    """Manage the autonomous background agent."""


@agent_group.command("start")
@click.option("--foreground", "-f", is_flag=True,
              help="Run in the foreground instead of as a background daemon.")
def agent_start(foreground: bool) -> None:
    """Start the autonomous agent."""
    from .daemon import start, status as daemon_status

    existing = daemon_status()
    if existing["running"]:
        click.echo(f"Agent already running (PID {existing['pid']})")
        return

    if foreground:
        click.echo("Starting agent in foreground (Ctrl-C to stop)…")
        start(foreground=True)
    else:
        pid = start(foreground=False)
        click.echo(f"Agent started in background (PID {pid})")
        click.echo(f"Logs: ~/.polymarket/agent.log")


@agent_group.command("stop")
def agent_stop() -> None:
    """Stop the background agent."""
    from .daemon import stop

    if stop():
        click.echo("Agent stopped.")
    else:
        click.echo("Agent was not running.")


@agent_group.command("status")
def agent_status() -> None:
    """Show agent status."""
    from .daemon import status as daemon_status

    info = daemon_status()
    if info["running"]:
        click.echo(f"Agent is RUNNING (PID {info['pid']})")
        if log := info.get("log"):
            click.echo(f"Log: {log}")
    else:
        click.echo("Agent is NOT running.")
        if stale := info.get("stale_pid"):
            click.echo(f"(stale PID file {stale} removed)")


@agent_group.command("run-once")
def agent_run_once() -> None:
    """Execute a single agent cycle (useful for testing)."""
    from .agent import PolymarketAgent

    cfg = Config.load()
    agent = PolymarketAgent(cfg)
    stats = agent.run_once()
    click.echo(
        f"\nCycle complete:\n"
        f"  Markets fetched    : {stats.markets_fetched}\n"
        f"  NegRisk opps       : {stats.negrisk_opps}\n"
        f"  Near-resolution    : {stats.near_res_opps}\n"
        f"  Claude analysed    : {stats.claude_analysed}\n"
        f"  Total traded       : {stats.total_traded}\n"
        f"  Errors             : {stats.errors}\n"
    )
