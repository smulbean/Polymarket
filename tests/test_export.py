"""Tests for polymarket_sdk.export."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from polymarket_sdk.export import (
    export_markets_to_csv,
    export_markets_to_json,
    export_orders_to_csv,
    export_positions_to_csv,
    export_to_csv,
    export_to_json,
)
from polymarket_sdk.models import Market, Order, Position


class TestExportToJson:
    def test_writes_json_file(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        out = tmp_dir / "markets.json"
        export_to_json([sample_market], out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data) == 1
        assert data[0]["id"] == "market_btc_100k"

    def test_creates_parent_directories(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        out = tmp_dir / "subdir" / "deep" / "markets.json"
        export_to_json([sample_market], out)
        assert out.exists()

    def test_returns_path_object(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        result = export_to_json([sample_market], tmp_dir / "out.json")
        assert isinstance(result, Path)

    def test_exports_multiple_items(
        self, sample_market: Market, sample_market_2: Market, tmp_dir: Path
    ) -> None:
        out = tmp_dir / "markets.json"
        export_to_json([sample_market, sample_market_2], out)
        data = json.loads(out.read_text())
        assert len(data) == 2


class TestExportToCsv:
    def test_writes_csv_file(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        out = tmp_dir / "markets.csv"
        export_to_csv([sample_market], out)
        assert out.exists()
        with open(out) as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["id"] == "market_btc_100k"

    def test_raises_value_error_on_empty_sequence(
        self, tmp_dir: Path
    ) -> None:
        with pytest.raises(ValueError, match="empty"):
            export_to_csv([], tmp_dir / "out.csv")

    def test_flattens_list_fields(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        out = tmp_dir / "markets.csv"
        export_to_csv([sample_market], out)
        with open(out) as fh:
            reader = csv.DictReader(fh)
            row = next(reader)
        # tags is a list — should be a comma-joined string
        assert isinstance(row["tags"], str)

    def test_exports_positions(
        self, sample_position: Position, tmp_dir: Path
    ) -> None:
        out = export_positions_to_csv([sample_position], tmp_dir / "pos.csv")
        assert out.exists()
        with open(out) as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert rows[0]["market_id"] == "market_btc_100k"

    def test_exports_orders(
        self, sample_order: Order, tmp_dir: Path
    ) -> None:
        out = export_orders_to_csv([sample_order], tmp_dir / "orders.csv")
        assert out.exists()

    def test_typed_wrapper_markets_json(
        self, sample_market: Market, tmp_dir: Path
    ) -> None:
        out = export_markets_to_json([sample_market], tmp_dir / "m.json")
        data = json.loads(out.read_text())
        assert data[0]["question"] == sample_market.question
