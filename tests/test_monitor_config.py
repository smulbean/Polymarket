"""Tests for monitor.config — config loading from env and file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor.config import Config


class TestConfigDefaults:
    def test_dry_run_is_true_by_default(self) -> None:
        cfg = Config()
        assert cfg.trading.dry_run is True

    def test_default_limits(self) -> None:
        cfg = Config()
        assert cfg.trading.max_per_trade == 20.0
        assert cfg.trading.max_per_day == 50.0
        assert cfg.trading.min_shares == 5.0

    def test_no_credentials_by_default(self) -> None:
        cfg = Config()
        assert cfg.has_trading_credentials is False


class TestConfigFromEnv:
    def test_private_key_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xdeadbeef")
        monkeypatch.setenv("POLYMARKET_PROXY_ADDRESS", "0xproxy")
        cfg = Config()
        cfg._apply_env()
        assert cfg.api.private_key == "0xdeadbeef"
        assert cfg.has_trading_credentials is True

    def test_dry_run_false_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("POLYMARKET_DRY_RUN", "false")
        cfg = Config()
        cfg._apply_env()
        assert cfg.trading.dry_run is False

    def test_max_per_trade_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("POLYMARKET_MAX_PER_TRADE", "100.0")
        cfg = Config()
        cfg._apply_env()
        assert cfg.trading.max_per_trade == 100.0


class TestConfigFromFile:
    def test_loads_from_file(self, tmp_path: Path, monkeypatch) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({
                "trading": {"max_per_trade": 50.0, "dry_run": False},
                "api": {"proxy_address": "0xtest"},
            })
        )
        monkeypatch.setattr("monitor.config.CONFIG_FILE", config_file)
        cfg = Config()
        cfg._apply_file()
        assert cfg.trading.max_per_trade == 50.0
        assert cfg.api.proxy_address == "0xtest"

    def test_missing_file_uses_defaults(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "monitor.config.CONFIG_FILE", tmp_path / "nonexistent.json"
        )
        cfg = Config()
        cfg._apply_file()
        assert cfg.trading.max_per_trade == 20.0


class TestSaveConfig:
    def test_save_does_not_write_private_key(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("monitor.config.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("monitor.config.CONFIG_FILE", tmp_path / "config.json")
        cfg = Config()
        cfg.api.private_key = "super_secret"
        cfg.save_non_sensitive()
        content = json.loads((tmp_path / "config.json").read_text())
        assert "private_key" not in str(content)
        assert "super_secret" not in str(content)
