"""
Interactive REPL for the Polymarket SDK.

Launch with ``polymarket-sdk repl`` or directly:

    python -m cli.repl

Commands mirror the Click CLI (search, positions, watchlist, etc.) so
users can experiment interactively without quoting shell arguments.
"""
from __future__ import annotations

import cmd
import json
import shlex
import sys
from typing import Optional

from polymarket_sdk import (
    CLINotFoundError,
    PolymarketError,
    get_positions,
    list_markets,
    search_markets,
)
from polymarket_sdk.session import Session


class PolymarketREPL(cmd.Cmd):
    """Interactive Polymarket REPL."""

    intro = (
        "\n"
        "  ╔══════════════════════════════╗\n"
        "  ║   Polymarket SDK  |  REPL    ║\n"
        "  ╚══════════════════════════════╝\n"
        "\n"
        "  Type 'help' to list commands, 'quit' to exit.\n"
    )
    prompt = "polymarket> "

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__()
        self._session = session or Session()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def do_search(self, line: str) -> None:
        """search <query> [--limit N]  — Search for markets."""
        parts = shlex.split(line) if line else []
        if not parts:
            print("Usage: search <query> [--limit N]")
            return

        query = parts[0]
        limit = None
        if "--limit" in parts:
            idx = parts.index("--limit")
            try:
                limit = int(parts[idx + 1])
            except (IndexError, ValueError):
                print("Error: --limit requires an integer value")
                return

        try:
            markets = search_markets(query, limit=limit)
        except CLINotFoundError as exc:
            print(f"[Error] CLI not available: {exc}")
            return
        except PolymarketError as exc:
            print(f"[Error] {exc}")
            return

        self._session.record_search(query)

        if not markets:
            print(f"No markets found for '{query}'")
            return

        print(f"\n  Found {len(markets)} market(s) for '{query}':\n")
        for m in markets:
            print(f"  [{m.id}] {m.question}")
            print(f"        YES={m.yes_price:.2f}  NO={m.no_price:.2f}  "
                  f"Vol=${m.volume:,.0f}  Status={m.status}")
        print()

    def do_list(self, line: str) -> None:
        """list [--status active|resolved] [--category <cat>] [--limit N]  — List markets."""
        parts = shlex.split(line) if line else []
        kwargs: dict = {}

        def _extract(flag: str) -> Optional[str]:
            if flag in parts:
                idx = parts.index(flag)
                try:
                    return parts[idx + 1]
                except IndexError:
                    return None
            return None

        if (s := _extract("--status")):
            kwargs["status"] = s
        if (c := _extract("--category")):
            kwargs["category"] = c
        if (lim := _extract("--limit")):
            try:
                kwargs["limit"] = int(lim)
            except ValueError:
                print("Error: --limit requires an integer")
                return

        try:
            markets = list_markets(**kwargs)
        except CLINotFoundError as exc:
            print(f"[Error] CLI not available: {exc}")
            return
        except PolymarketError as exc:
            print(f"[Error] {exc}")
            return

        print(f"\n  {len(markets)} market(s):\n")
        for m in markets:
            print(f"  [{m.id}] {m.question}  ({m.status})")
        print()

    def do_positions(self, _line: str) -> None:
        """positions  — Show current open positions."""
        try:
            positions = get_positions()
        except CLINotFoundError as exc:
            print(f"[Error] CLI not available: {exc}")
            return
        except PolymarketError as exc:
            print(f"[Error] {exc}")
            return

        if not positions:
            print("No open positions.")
            return

        print(f"\n  {len(positions)} position(s):\n")
        for p in positions:
            pnl_sign = "+" if p.pnl >= 0 else ""
            print(
                f"  [{p.market_id}] {p.market_question}\n"
                f"        {p.outcome}  size={p.size:.2f}  "
                f"avg={p.avg_price:.3f}  cur={p.current_price:.3f}  "
                f"pnl={pnl_sign}{p.pnl:.2f}"
            )
        print()

    def do_watchlist(self, line: str) -> None:
        """watchlist [add <id> | remove <id> | show]  — Manage your watchlist."""
        parts = shlex.split(line) if line else []
        sub = parts[0].lower() if parts else "show"

        if sub == "show" or sub == "":
            wl = self._session.watchlist
            if not wl:
                print("Watchlist is empty.")
            else:
                print(f"\n  Watchlist ({len(wl)} items):")
                for mid in wl:
                    print(f"    - {mid}")
            print()

        elif sub == "add":
            if len(parts) < 2:
                print("Usage: watchlist add <market_id>")
                return
            market_id = parts[1]
            if self._session.add_to_watchlist(market_id):
                print(f"Added {market_id!r} to watchlist.")
            else:
                print(f"{market_id!r} is already in your watchlist.")

        elif sub == "remove":
            if len(parts) < 2:
                print("Usage: watchlist remove <market_id>")
                return
            market_id = parts[1]
            if self._session.remove_from_watchlist(market_id):
                print(f"Removed {market_id!r} from watchlist.")
            else:
                print(f"{market_id!r} was not in your watchlist.")

        else:
            print(f"Unknown watchlist sub-command: {sub!r}")

    def do_history(self, _line: str) -> None:
        """history  — Show recent search queries."""
        searches = self._session.recent_searches
        if not searches:
            print("No recent searches.")
            return
        print("\n  Recent searches (most recent last):")
        for i, q in enumerate(searches, 1):
            print(f"    {i:2d}. {q}")
        print()

    def do_quit(self, _line: str) -> bool:  # type: ignore[override]
        """quit  — Exit the REPL."""
        print("Goodbye.")
        return True

    # Aliases
    do_exit = do_quit
    do_q = do_quit

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def default(self, line: str) -> None:
        print(f"Unknown command: {line.split()[0]!r}  (type 'help' to list commands)")

    def emptyline(self) -> None:
        pass  # Don't repeat the last command on empty input.
