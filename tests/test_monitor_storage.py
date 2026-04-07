"""Tests for monitor.storage — JSONL persistence utilities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor.storage import (
    append_record,
    iter_records,
    load_price_history,
    load_trades,
    overwrite_records,
    read_records,
    save_price_point,
    save_trade,
    update_trade,
)
from monitor import storage as st


@pytest.fixture(autouse=True)
def redirect_storage(tmp_path: Path, monkeypatch):
    """Redirect all storage paths to a temp directory for isolation."""
    monkeypatch.setattr(st, "DATA_DIR", tmp_path)
    monkeypatch.setattr(st, "TRADES_FILE", tmp_path / "trades.jsonl")
    monkeypatch.setattr(st, "SNAPSHOTS_FILE", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(st, "LESSONS_FILE", tmp_path / "lessons.jsonl")
    monkeypatch.setattr(st, "PRICES_DIR", tmp_path / "prices")
    (tmp_path / "prices").mkdir()


class TestReadWriteRecords:
    def test_append_and_read(self, tmp_path: Path) -> None:
        path = tmp_path / "test.jsonl"
        append_record(path, {"key": "value", "n": 42})
        records = read_records(path)
        assert len(records) == 1
        assert records[0]["key"] == "value"

    def test_multiple_appends(self, tmp_path: Path) -> None:
        path = tmp_path / "multi.jsonl"
        for i in range(5):
            append_record(path, {"i": i})
        assert len(read_records(path)) == 5

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_records(tmp_path / "nonexistent.jsonl") == []

    def test_overwrite_replaces_contents(self, tmp_path: Path) -> None:
        path = tmp_path / "ow.jsonl"
        append_record(path, {"old": True})
        overwrite_records(path, [{"new": True}, {"new": True}])
        records = read_records(path)
        assert len(records) == 2
        assert all(r["new"] is True for r in records)

    def test_iter_records(self, tmp_path: Path) -> None:
        path = tmp_path / "iter.jsonl"
        for i in range(3):
            append_record(path, {"i": i})
        result = list(iter_records(path))
        assert len(result) == 3


class TestTrades:
    def test_save_and_load_trade(self) -> None:
        save_trade({"trade_id": "t1", "cost": 10.0, "status": "open"})
        trades = load_trades()
        assert len(trades) == 1
        assert trades[0]["trade_id"] == "t1"

    def test_update_trade(self) -> None:
        save_trade({"trade_id": "t2", "status": "open", "pnl": 0.0})
        result = update_trade("t2", {"status": "won", "pnl": 5.0})
        assert result is True
        trades = load_trades()
        assert trades[0]["status"] == "won"
        assert trades[0]["pnl"] == 5.0

    def test_update_nonexistent_trade_returns_false(self) -> None:
        assert update_trade("NOPE", {"status": "won"}) is False


class TestPriceHistory:
    def test_save_and_load_price_point(self) -> None:
        save_price_point("market_123", {"yes_price": 0.45, "no_price": 0.55})
        history = load_price_history("market_123")
        assert len(history) == 1
        assert history[0]["yes_price"] == 0.45

    def test_multiple_price_points_accumulate(self) -> None:
        for price in [0.40, 0.42, 0.45]:
            save_price_point("m_abc", {"yes_price": price})
        history = load_price_history("m_abc")
        assert len(history) == 3

    def test_different_markets_stored_separately(self) -> None:
        save_price_point("market_A", {"yes_price": 0.50})
        save_price_point("market_B", {"yes_price": 0.80})
        assert len(load_price_history("market_A")) == 1
        assert len(load_price_history("market_B")) == 1
