"""Tests for monitor.telegram_notifier — Telegram Bot API sender."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from monitor.telegram_notifier import TelegramNotifier, _send


class TestSend:
    def test_returns_false_without_token(self) -> None:
        assert _send("", "123", "hello") is False

    def test_returns_false_without_chat_id(self) -> None:
        assert _send("token", "", "hello") is False

    def test_returns_false_when_requests_missing(self) -> None:
        with patch("monitor.telegram_notifier._HAVE_REQUESTS", False):
            assert _send("token", "123", "hello") is False

    def test_returns_true_on_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp

        with patch("monitor.telegram_notifier._HAVE_REQUESTS", True), \
             patch("monitor.telegram_notifier._requests", mock_requests):
            result = _send("token", "123", "hello")

        assert result is True
        mock_requests.post.assert_called_once()

    def test_returns_false_on_non_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_resp

        with patch("monitor.telegram_notifier._HAVE_REQUESTS", True), \
             patch("monitor.telegram_notifier._requests", mock_requests):
            result = _send("token", "123", "hello")

        assert result is False

    def test_returns_false_on_network_error(self) -> None:
        mock_requests = MagicMock()
        mock_requests.post.side_effect = ConnectionError("timeout")

        with patch("monitor.telegram_notifier._HAVE_REQUESTS", True), \
             patch("monitor.telegram_notifier._requests", mock_requests):
            result = _send("token", "123", "hello")

        assert result is False


class TestTelegramNotifier:
    def _notifier(self) -> TelegramNotifier:
        return TelegramNotifier(token="test_token", chat_id="test_chat")

    def test_send_trade_alert_dry_run(self) -> None:
        n = self._notifier()
        trade = {
            "dry_run": True,
            "question": "Will BTC exceed $100k?",
            "strategy": "negrisk_arb",
            "side": "buy",
            "shares": 5.0,
            "cost": 4.50,
        }
        with patch.object(n, "send", return_value=True) as mock_send:
            n.send_trade_alert(trade)
        text = mock_send.call_args[0][0]
        assert "DRY RUN" in text
        assert "negrisk_arb" in text

    def test_send_trade_alert_live(self) -> None:
        n = self._notifier()
        trade = {
            "dry_run": False,
            "question": "Live market",
            "strategy": "conviction",
            "side": "buy",
            "shares": 10.0,
            "cost": 9.50,
        }
        with patch.object(n, "send", return_value=True) as mock_send:
            n.send_trade_alert(trade)
        text = mock_send.call_args[0][0]
        assert "TRADE PLACED" in text

    def test_send_cycle_summary(self) -> None:
        n = self._notifier()
        with patch.object(n, "send", return_value=True) as mock_send:
            n.send_cycle_summary(
                cycle_num=3,
                opportunities=5,
                trades_placed=2,
                errors=0,
                top_opportunities=["Opp A", "Opp B"],
            )
        text = mock_send.call_args[0][0]
        assert "Cycle #3" in text
        assert "Opp A" in text

    def test_send_error(self) -> None:
        n = self._notifier()
        with patch.object(n, "send", return_value=True) as mock_send:
            n.send_error("main loop", "Connection refused")
        text = mock_send.call_args[0][0]
        assert "Error" in text
        assert "Connection refused" in text

    def test_send_startup_dry_run(self) -> None:
        n = self._notifier()
        with patch.object(n, "send", return_value=True) as mock_send:
            n.send_startup(dry_run=True, scan_interval=300)
        text = mock_send.call_args[0][0]
        assert "DRY RUN" in text
        assert "300s" in text

    def test_from_config(self) -> None:
        from monitor.config import Config
        cfg = Config()
        cfg.notifications.telegram_bot_token = "tok"
        cfg.notifications.telegram_chat_id = "cid"
        n = TelegramNotifier.from_config(cfg)
        assert n._token == "tok"
        assert n._chat_id == "cid"
