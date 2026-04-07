"""
Click-based CLI for the Polymarket SDK.

Entry point: ``polymarket-sdk``  (configured in pyproject.toml)

Commands
--------
  polymarket-sdk markets search <query>
  polymarket-sdk markets get <id>
  polymarket-sdk markets list
  polymarket-sdk events list
  polymarket-sdk events get <id>
  polymarket-sdk orders place
  polymarket-sdk orders cancel <id>
  polymarket-sdk orders list
  polymarket-sdk positions
  polymarket-sdk watchlist add <id>
  polymarket-sdk watchlist remove <id>
  polymarket-sdk watchlist show
  polymarket-sdk export markets <output>
  polymarket-sdk export positions <output>
  polymarket-sdk repl
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from polymarket_sdk import (
    CLINotFoundError,
    PolymarketError,
    cancel_order,
    export_markets_to_csv,
    export_markets_to_json,
    export_positions_to_csv,
    export_positions_to_json,
    get_event,
    get_market,
    get_orders,
    get_positions,
    get_price,
    get_price_history,
    list_events,
    list_markets,
    place_order,
    search_markets,
)
from polymarket_sdk.session import Session

try:
    from rich.console import Console
    from rich.table import Table

    _console = Console()
    _err_console = Console(stderr=True, style="bold red")
    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False

# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version="0.1.0", prog_name="polymarket-sdk")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """Polymarket SDK CLI — interact with Polymarket prediction markets."""
    ctx.ensure_object(dict)
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    ctx.obj["session"] = Session()


# ---------------------------------------------------------------------------
# markets group
# ---------------------------------------------------------------------------


@cli.group("markets")
def markets_group() -> None:
    """Market-related commands."""


@markets_group.command("search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Maximum results.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def markets_search(query: str, limit: int, as_json: bool) -> None:
    """Search for markets matching QUERY."""
    try:
        results = search_markets(query, limit=limit)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([m.to_dict() for m in results], indent=2))
        return

    if not results:
        click.echo(f"No markets found for '{query}'")
        return

    _print_markets_table(results, title=f"Markets matching '{query}'")


@markets_group.command("get")
@click.argument("market_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def markets_get(market_id: str, as_json: bool) -> None:
    """Fetch a single market by MARKET_ID."""
    try:
        market = get_market(market_id)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(market.to_dict(), indent=2))
        return

    _print_markets_table([market], title="Market Details")


@markets_group.command("list")
@click.option("--status", default=None, help="Filter by status (active/resolved/closed).")
@click.option("--category", default=None, help="Filter by category slug.")
@click.option("--limit", default=20, show_default=True, help="Maximum results.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def markets_list(
    status: Optional[str], category: Optional[str], limit: int, as_json: bool
) -> None:
    """List all markets."""
    try:
        results = list_markets(status=status, category=category, limit=limit)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([m.to_dict() for m in results], indent=2))
        return

    _print_markets_table(results, title="Markets")


# ---------------------------------------------------------------------------
# events group
# ---------------------------------------------------------------------------


@cli.group("events")
def events_group() -> None:
    """Event-related commands."""


@events_group.command("list")
@click.option("--category", default=None, help="Filter by category slug.")
@click.option("--limit", default=20, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def events_list(category: Optional[str], limit: int, as_json: bool) -> None:
    """List all events."""
    try:
        results = list_events(category=category, limit=limit)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([e.to_dict() for e in results], indent=2))
        return

    if not results:
        click.echo("No events found.")
        return

    for evt in results:
        click.echo(f"  [{evt.id}]  {evt.title}  ({evt.category})")


@events_group.command("get")
@click.argument("event_id")
@click.option("--json", "as_json", is_flag=True)
def events_get(event_id: str, as_json: bool) -> None:
    """Fetch a single event by EVENT_ID."""
    try:
        evt = get_event(event_id)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(evt.to_dict(), indent=2))
        return

    click.echo(f"\n  {evt.title}  [{evt.id}]")
    click.echo(f"  Category : {evt.category}")
    click.echo(f"  Markets  : {len(evt.markets)}")
    for m in evt.markets:
        click.echo(f"    - [{m.id}] {m.question}")
    click.echo()


# ---------------------------------------------------------------------------
# orders group
# ---------------------------------------------------------------------------


@cli.group("orders")
def orders_group() -> None:
    """Order management commands."""


@orders_group.command("place")
@click.option("--market", "market_id", required=True, help="Market ID.")
@click.option("--outcome", required=True, type=click.Choice(["YES", "NO"]))
@click.option("--side", required=True, type=click.Choice(["buy", "sell"]))
@click.option("--price", required=True, type=float, help="Limit price (0–1).")
@click.option("--size", required=True, type=float, help="Number of shares.")
@click.option("--json", "as_json", is_flag=True)
def orders_place(
    market_id: str,
    outcome: str,
    side: str,
    price: float,
    size: float,
    as_json: bool,
) -> None:
    """Place a limit order."""
    try:
        result = place_order(market_id, outcome, side, price, size)
    except (ValueError, CLINotFoundError) as exc:
        _error(str(exc))
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    click.echo(f"Order {result.order_id!r} — {result.status}: {result.message}")


@orders_group.command("cancel")
@click.argument("order_id")
@click.option("--json", "as_json", is_flag=True)
def orders_cancel(order_id: str, as_json: bool) -> None:
    """Cancel an open order by ORDER_ID."""
    try:
        result = cancel_order(order_id)
    except (ValueError, CLINotFoundError) as exc:
        _error(str(exc))
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    click.echo(f"Order {result.order_id!r} — {result.status}: {result.message}")


@orders_group.command("list")
@click.option("--market", "market_id", default=None)
@click.option("--status", default=None, type=click.Choice(["open", "filled", "cancelled"]))
@click.option("--json", "as_json", is_flag=True)
def orders_list(market_id: Optional[str], status: Optional[str], as_json: bool) -> None:
    """List orders."""
    try:
        orders = get_orders(market_id=market_id, status=status)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([o.to_dict() for o in orders], indent=2))
        return

    if not orders:
        click.echo("No orders found.")
        return

    for o in orders:
        click.echo(
            f"  [{o.id}] {o.market_id}  {o.outcome}  {o.side}  "
            f"price={o.price:.3f}  size={o.size:.2f}  status={o.status}"
        )


# ---------------------------------------------------------------------------
# positions command
# ---------------------------------------------------------------------------


@cli.command("positions")
@click.option("--json", "as_json", is_flag=True)
def positions_cmd(as_json: bool) -> None:
    """Show current positions."""
    try:
        positions = get_positions()
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([p.to_dict() for p in positions], indent=2))
        return

    if not positions:
        click.echo("No open positions.")
        return

    for p in positions:
        pnl_sign = "+" if p.pnl >= 0 else ""
        click.echo(
            f"  [{p.market_id}] {p.market_question}\n"
            f"        {p.outcome}  size={p.size:.2f}  avg={p.avg_price:.3f}  "
            f"pnl={pnl_sign}{p.pnl:.2f}"
        )


# ---------------------------------------------------------------------------
# watchlist group
# ---------------------------------------------------------------------------


@cli.group("watchlist")
@click.pass_context
def watchlist_group(ctx: click.Context) -> None:
    """Manage your market watchlist."""


@watchlist_group.command("add")
@click.argument("market_id")
@click.pass_context
def watchlist_add(ctx: click.Context, market_id: str) -> None:
    """Add MARKET_ID to your watchlist."""
    session: Session = ctx.obj["session"]
    if session.add_to_watchlist(market_id):
        click.echo(f"Added {market_id!r} to watchlist.")
    else:
        click.echo(f"{market_id!r} is already in your watchlist.")


@watchlist_group.command("remove")
@click.argument("market_id")
@click.pass_context
def watchlist_remove(ctx: click.Context, market_id: str) -> None:
    """Remove MARKET_ID from your watchlist."""
    session: Session = ctx.obj["session"]
    if session.remove_from_watchlist(market_id):
        click.echo(f"Removed {market_id!r} from watchlist.")
    else:
        click.echo(f"{market_id!r} was not in your watchlist.")


@watchlist_group.command("show")
@click.pass_context
def watchlist_show(ctx: click.Context) -> None:
    """Display all watchlist entries."""
    session: Session = ctx.obj["session"]
    wl = session.watchlist
    if not wl:
        click.echo("Watchlist is empty.")
        return
    click.echo(f"\n  Watchlist ({len(wl)} items):")
    for mid in wl:
        click.echo(f"    - {mid}")
    click.echo()


# ---------------------------------------------------------------------------
# export group
# ---------------------------------------------------------------------------


@cli.group("export")
def export_group() -> None:
    """Export data to CSV or JSON files."""


@export_group.command("markets")
@click.argument("output")
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json"]))
@click.option("--query", default=None, help="Search query (optional).")
@click.option("--limit", default=50, show_default=True)
def export_markets(output: str, fmt: str, query: Optional[str], limit: int) -> None:
    """Export markets to OUTPUT file."""
    try:
        if query:
            mlist = search_markets(query, limit=limit)
        else:
            mlist = list_markets(limit=limit)
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if fmt == "json":
        path = export_markets_to_json(mlist, output)
    else:
        path = export_markets_to_csv(mlist, output)

    click.echo(f"Exported {len(mlist)} markets to {path}")


@export_group.command("positions")
@click.argument("output")
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json"]))
def export_positions_cmd(output: str, fmt: str) -> None:
    """Export positions to OUTPUT file."""
    try:
        plist = get_positions()
    except CLINotFoundError as exc:
        _error(f"CLI not found: {exc}")
        sys.exit(1)
    except PolymarketError as exc:
        _error(str(exc))
        sys.exit(1)

    if fmt == "json":
        path = export_positions_to_json(plist, output)
    else:
        path = export_positions_to_csv(plist, output)

    click.echo(f"Exported {len(plist)} positions to {path}")


# ---------------------------------------------------------------------------
# repl command
# ---------------------------------------------------------------------------


@cli.command("repl")
def repl_cmd() -> None:
    """Start the interactive REPL."""
    from cli.repl import PolymarketREPL

    PolymarketREPL().cmdloop()


# ---------------------------------------------------------------------------
# Monitor sub-group (Phases 3–7)
# ---------------------------------------------------------------------------

from monitor.cli import monitor_group  # noqa: E402

cli.add_command(monitor_group)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _print_markets_table(markets: list, title: str = "Markets") -> None:
    if _RICH:
        table = Table(title=title, show_lines=False)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Question", style="white")
        table.add_column("YES", style="green", justify="right")
        table.add_column("NO", style="red", justify="right")
        table.add_column("Volume", justify="right")
        table.add_column("Status")
        for m in markets:
            table.add_row(
                m.id,
                m.question[:60] + ("…" if len(m.question) > 60 else ""),
                f"{m.yes_price:.3f}",
                f"{m.no_price:.3f}",
                f"${m.volume:,.0f}",
                m.status,
            )
        _console.print(table)
    else:
        click.echo(f"\n{title}:")
        for m in markets:
            click.echo(
                f"  [{m.id}] {m.question}  "
                f"YES={m.yes_price:.3f}  NO={m.no_price:.3f}  "
                f"vol=${m.volume:,.0f}  {m.status}"
            )
        click.echo()


def _error(message: str) -> None:
    if _RICH:
        _err_console.print(f"[bold red]Error:[/bold red] {message}")
    else:
        click.echo(f"Error: {message}", err=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
