"""Tests for monitor.executor — guardrails and trade execution."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from monitor.config import Config, TradingConfig
from monitor.executor import (
    DailyLimitError,
    Executor,
    MinSizeError,
    PerTradeLimitError,
)
from monitor.models import TradeRecord


def _make_executor(tmp_path: Path, dry_run: bool = True, **kwargs) -> Executor:
    cfg = Config()
    cfg.trading.dry_run = dry_run
    cfg.trading.max_per_trade = kwargs.get("max_per_trade", 20.0)
    cfg.trading.max_per_day = kwargs.get("max_per_day", 50.0)
    cfg.trading.min_shares = kwargs.get("min_shares", 5.0)

    backend = MagicMock()
    executor = Executor(config=cfg, backend=backend)

    # Redirect trade log to tmp_path
    from monitor import storage
    storage.TRADES_FILE = tmp_path / "trades.jsonl"
    return executor


class TestGuardrails:
    def test_min_size_check(self, tmp_path: Path) -> None:
        ex = _make_executor(tmp_path, min_shares=5.0)
        with pytest.raises(MinSizeError, match="minimum"):
            ex.execute("tok1", "YES", "buy", price=0.50, size=2.0)

    def test_per_trade_limit(self, tmp_path: Path) -> None:
        # cost = 0.60 * 50 = $30 > $20 limit
        ex = _make_executor(tmp_path, max_per_trade=20.0)
        with pytest.raises(PerTradeLimitError, match="per-trade limit"):
            ex.execute("tok1", "YES", "buy", price=0.60, size=50.0)

    def test_daily_limit(self, tmp_path: Path) -> None:
        from monitor import storage as st
        st.TRADES_FILE = tmp_path / "trades.jsonl"

        cfg = Config()
        cfg.trading.dry_run = False
        cfg.trading.max_per_trade = 30.0
        cfg.trading.max_per_day = 25.0
        cfg.trading.min_shares = 5.0
        cfg.api.private_key = "0xdeadbeef"
        cfg.api.proxy_address = "0xproxy"
        backend = MagicMock()
        ex = Executor(config=cfg, backend=backend)

        # Simulate $20 already spent today
        from monitor.storage import save_trade, now_iso
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat() + "T12:00:00+00:00"
        save_trade({
            "trade_id": "prev",
            "timestamp": today,
            "cost": 20.0,
            "status": "open",
            "dry_run": False,
        })

        # Adding another $10 → total $30 > $25 daily limit
        with pytest.raises(DailyLimitError, match="Daily limit"):
            ex.execute("tok1", "YES", "buy", price=0.50, size=20.0)

    def test_dry_run_does_not_call_backend(self, tmp_path: Path) -> None:
        ex = _make_executor(tmp_path, dry_run=True)
        record = ex.execute(
            "tok1", "YES", "buy", price=0.45, size=10.0,
            market_question="Will X happen?",
        )
        assert record.dry_run is True
        assert record.order_id == "DRY_RUN"
        ex.backend.place_order.assert_not_called()

    def test_dry_run_record_saved(self, tmp_path: Path) -> None:
        from monitor import storage as st
        st.TRADES_FILE = tmp_path / "trades.jsonl"

        ex = _make_executor(tmp_path, dry_run=True)
        ex.execute("tok1", "YES", "buy", price=0.45, size=10.0)
        from monitor.storage import load_trades
        trades = load_trades()
        assert len(trades) == 1
        assert trades[0]["dry_run"] is True


class TestDailySummary:
    def test_daily_summary_structure(self, tmp_path: Path) -> None:
        ex = _make_executor(tmp_path)
        summary = ex.daily_summary()
        assert "date" in summary
        assert "remaining_today" in summary
        assert "daily_limit" in summary

    def test_dry_run_not_counted_in_spend(self, tmp_path: Path) -> None:
        from monitor import storage as st
        st.TRADES_FILE = tmp_path / "trades.jsonl"

        from monitor.storage import save_trade, now_iso
        save_trade({
            "trade_id": "dry1",
            "timestamp": now_iso(),
            "cost": 40.0,
            "status": "open",
            "dry_run": True,    # ← dry run, should not count
        })
        ex = _make_executor(tmp_path, max_per_day=50.0)
        assert ex._daily_spend() == 0.0


class TestNegRiskExecution:
    def test_execute_negrisk_arb_dry_run(self, tmp_path: Path) -> None:
        from monitor import storage as st
        st.TRADES_FILE = tmp_path / "trades.jsonl"
        from monitor.models import MarketSnapshot

        markets = [
            MarketSnapshot(
                market_id=f"m{i}",
                question=f"Candidate {i} wins?",
                condition_id=f"c{i}",
                yes_token_id=f"yt{i}",
                no_token_id=f"nt{i}",
                yes_price=0.25,
                no_price=0.75,
                volume=0,
                liquidity=0,
                end_date="",
                status="active",
                neg_risk=True,
                neg_risk_market_id="grp1",
            )
            for i in range(3)
        ]
        ex = _make_executor(tmp_path, dry_run=True)
        records = ex.execute_negrisk_arb(markets, sets=5)
        assert len(records) == 3
        assert all(r.strategy == "negrisk_arb" for r in records)
        assert all(r.dry_run is True for r in records)
