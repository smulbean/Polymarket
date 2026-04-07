"""
Integration-style tests for the Click CLI (cli/main.py).

Uses click.testing.CliRunner so no subprocess is involved.
The SDK functions are patched to return fixture data.
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cli.main import cli
from polymarket_sdk.models import Market, Order, OrderResult, Position


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def market(market_dict: Dict[str, Any]) -> Market:
    return Market.from_dict(market_dict)


@pytest.fixture
def position(position_dict: Dict[str, Any]) -> Position:
    return Position.from_dict(position_dict)


@pytest.fixture
def order_result(order_result_dict: Dict[str, Any]) -> OrderResult:
    return OrderResult.from_dict(order_result_dict)


# ---------------------------------------------------------------------------
# markets search
# ---------------------------------------------------------------------------


class TestMarketsSearch:
    def test_search_outputs_market(
        self, runner: CliRunner, market: Market
    ) -> None:
        with patch("cli.main.search_markets", return_value=[market]):
            result = runner.invoke(cli, ["markets", "search", "bitcoin"])
        assert result.exit_code == 0
        assert "bitcoin" in result.output.lower() or "btc" in result.output.lower() or market.id in result.output

    def test_search_json_output(
        self, runner: CliRunner, market: Market
    ) -> None:
        with patch("cli.main.search_markets", return_value=[market]):
            result = runner.invoke(cli, ["markets", "search", "bitcoin", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["id"] == market.id

    def test_search_no_results_message(self, runner: CliRunner) -> None:
        with patch("cli.main.search_markets", return_value=[]):
            result = runner.invoke(cli, ["markets", "search", "zzz"])
        assert result.exit_code == 0
        assert "No markets found" in result.output

    def test_cli_not_found_exits_1(self, runner: CliRunner) -> None:
        from polymarket_sdk import CLINotFoundError

        with patch("cli.main.search_markets", side_effect=CLINotFoundError("missing")):
            result = runner.invoke(cli, ["markets", "search", "btc"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------


class TestPositionsCommand:
    def test_positions_json_output(
        self, runner: CliRunner, position: Position
    ) -> None:
        with patch("cli.main.get_positions", return_value=[position]):
            result = runner.invoke(cli, ["positions", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["market_id"] == position.market_id

    def test_empty_positions_message(self, runner: CliRunner) -> None:
        with patch("cli.main.get_positions", return_value=[]):
            result = runner.invoke(cli, ["positions"])
        assert result.exit_code == 0
        assert "No open positions" in result.output


# ---------------------------------------------------------------------------
# watchlist
# ---------------------------------------------------------------------------


class TestWatchlistCommands:
    def test_watchlist_add_and_show(
        self, runner: CliRunner, tmp_path: Any
    ) -> None:
        from polymarket_sdk.session import Session

        session = Session(path=tmp_path / "s.json")
        with patch("cli.main.Session", return_value=session):
            result = runner.invoke(cli, ["watchlist", "add", "market_xyz"])
        assert result.exit_code == 0
        assert "Added" in result.output

    def test_watchlist_show_empty(
        self, runner: CliRunner, tmp_path: Any
    ) -> None:
        from polymarket_sdk.session import Session

        session = Session(path=tmp_path / "s.json")
        with patch("cli.main.Session", return_value=session):
            result = runner.invoke(cli, ["watchlist", "show"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()


# ---------------------------------------------------------------------------
# orders place
# ---------------------------------------------------------------------------


class TestOrdersPlace:
    def test_place_order_success(
        self, runner: CliRunner, order_result: OrderResult
    ) -> None:
        with patch("cli.main.place_order", return_value=order_result):
            result = runner.invoke(
                cli,
                [
                    "orders",
                    "place",
                    "--market", "market_btc_100k",
                    "--outcome", "YES",
                    "--side", "buy",
                    "--price", "0.45",
                    "--size", "100",
                ],
            )
        assert result.exit_code == 0
        assert order_result.order_id in result.output

    def test_place_order_json_output(
        self, runner: CliRunner, order_result: OrderResult
    ) -> None:
        with patch("cli.main.place_order", return_value=order_result):
            result = runner.invoke(
                cli,
                [
                    "orders", "place",
                    "--market", "m1",
                    "--outcome", "YES",
                    "--side", "buy",
                    "--price", "0.5",
                    "--size", "10",
                    "--json",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["order_id"] == order_result.order_id
