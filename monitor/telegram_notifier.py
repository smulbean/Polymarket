"""
Telegram notification sender.

Uses the Telegram Bot API (no third-party library — just requests) to
send formatted messages to a chat.  All messages are best-effort: errors
are logged but never raised so they never crash the agent loop.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

try:
    import requests as _requests
    _HAVE_REQUESTS = True
except ImportError:
    _HAVE_REQUESTS = False

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10  # seconds


def _send(token: str, chat_id: str, text: str) -> bool:
    """Low-level send. Returns True on success."""
    if not _HAVE_REQUESTS:
        logger.warning("requests not installed — Telegram notifications disabled")
        return False
    if not token or not chat_id:
        return False

    url = _TELEGRAM_API.format(token=token)
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = _requests.post(url, json=payload, timeout=_TIMEOUT)
        if not resp.ok:
            logger.warning("Telegram API error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


class TelegramNotifier:
    """
    Sends formatted Polymarket alerts to a Telegram chat.

    Usage::

        n = TelegramNotifier.from_config(cfg)
        n.send_trade_alert(trade)
        n.send_cycle_summary(opportunities, trades_placed)
    """

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    @classmethod
    def from_config(cls, cfg: "Config") -> "TelegramNotifier":  # noqa: F821
        return cls(
            token=cfg.notifications.telegram_bot_token,
            chat_id=cfg.notifications.telegram_chat_id,
        )

    def send(self, text: str) -> bool:
        return _send(self._token, self._chat_id, text)

    # ------------------------------------------------------------------
    # Formatted messages
    # ------------------------------------------------------------------

    def send_trade_alert(self, trade: Dict[str, Any]) -> bool:
        """Alert for a placed (or dry-run) trade."""
        dry = trade.get("dry_run", True)
        prefix = "🔵 DRY RUN" if dry else "🟢 TRADE PLACED"
        market_q = trade.get("question", trade.get("market_id", "?"))
        side = trade.get("side", "?")
        shares = trade.get("shares", 0)
        cost = trade.get("cost", 0)
        strategy = trade.get("strategy", "unknown")

        text = (
            f"<b>{prefix}</b>\n"
            f"📊 <b>Market:</b> {market_q}\n"
            f"📌 <b>Strategy:</b> {strategy}\n"
            f"💱 <b>Side:</b> {side}  |  "
            f"<b>Shares:</b> {shares:.1f}  |  "
            f"<b>Cost:</b> ${cost:.2f}"
        )
        if reason := trade.get("reason"):
            text += f"\n💡 {reason}"
        return self.send(text)

    def send_cycle_summary(
        self,
        cycle_num: int,
        opportunities: int,
        trades_placed: int,
        errors: int,
        top_opportunities: Optional[List[str]] = None,
    ) -> bool:
        """End-of-cycle summary."""
        text = (
            f"<b>🔄 Agent Cycle #{cycle_num} Complete</b>\n"
            f"🎯 Opportunities found: <b>{opportunities}</b>\n"
            f"✅ Trades placed: <b>{trades_placed}</b>\n"
            f"❌ Errors: <b>{errors}</b>"
        )
        if top_opportunities:
            text += "\n\n<b>Top opportunities:</b>"
            for opp in top_opportunities[:3]:
                text += f"\n• {opp}"
        return self.send(text)

    def send_error(self, context: str, error: str) -> bool:
        """Error notification."""
        text = f"⚠️ <b>Agent Error</b>\n<b>Context:</b> {context}\n<code>{error[:400]}</code>"
        return self.send(text)

    def send_startup(self, dry_run: bool, scan_interval: int) -> bool:
        mode = "DRY RUN" if dry_run else "LIVE TRADING"
        text = (
            f"🚀 <b>Polymarket Agent Started</b>\n"
            f"Mode: <b>{mode}</b>\n"
            f"Scan interval: {scan_interval}s"
        )
        return self.send(text)

    def send_shutdown(self) -> bool:
        return self.send("🛑 <b>Polymarket Agent Stopped</b>")
