"""
Configuration management for the Polymarket monitor system.

Priority order (highest wins):
  1. Environment variables  (POLYMARKET_*)
  2. ~/.polymarket/config.json
  3. Hard-coded defaults

Sensitive values (private key, passphrase) are never written to disk
by this module — they must come from environment variables or a .env file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CONFIG_DIR = Path.home() / ".polymarket"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class APIConfig:
    """Credentials for the Polymarket CLOB trading API."""

    # Wallet private key — ONLY from env, never from file.
    private_key: str = ""
    # The proxy address that polymarket.com created (the "funder").
    proxy_address: str = ""
    host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    data_host: str = "https://data-api.polymarket.com"
    chain_id: int = 137              # Polygon mainnet
    # signature_type=2 → Gnosis Safe, matching the web proxy.
    signature_type: int = 2

    # L2 CLOB API credentials (derived from private key via createOrDeriveApiKey).
    # Required for authenticated REST endpoints (order placement, cancellation).
    # ONLY from env, never from file.
    clob_api_key: str = ""
    clob_api_secret: str = ""
    clob_api_passphrase: str = ""


@dataclass
class TradingConfig:
    """Runtime guardrails for live trade execution."""

    max_per_trade: float = 20.0      # Maximum USD per single trade
    max_per_day: float = 50.0        # Maximum USD across all trades in a day
    min_shares: float = 5.0          # Polymarket minimum order size
    dry_run: bool = True             # NEVER live-trade unless explicitly False
    # Minimum ROI threshold to flag an opportunity as actionable.
    min_roi_threshold: float = 0.05  # 5%


@dataclass
class MonitorConfig:
    """Settings for the price monitor loop."""

    watchlist_refresh_interval: int = 300     # seconds (5 min)
    price_history_days: int = 7
    alert_cooldown_seconds: int = 900         # don't re-alert for 15 min
    max_opportunities: int = 10
    near_resolution_hours: int = 24
    near_resolution_min_confidence: float = 0.90


@dataclass
class ClaudeAnalystConfig:
    """Anthropic Claude API settings for AI-powered market analysis."""

    api_key: str = ""
    model: str = "claude-opus-4-6"
    max_tokens: int = 1024
    # Minimum edge (|prob - price|) required before recommending a trade.
    min_edge: float = 0.10
    # Minimum Claude confidence score to act on a recommendation.
    min_confidence: float = 0.70


@dataclass
class AgentConfig:
    """Settings for the autonomous background agent."""

    scan_interval_seconds: int = 300       # 5 minutes between cycles
    max_markets_per_cycle: int = 8         # GPT calls per cycle (cost control)
    min_liquidity: float = 10_000.0        # skip thin markets
    resolution_window_days: int = 7        # only analyze markets resolving within N days
    enable_claude_analysis: bool = True    # use Claude API for analysis
    enable_negrisk_scan: bool = True       # scan NegRisk arbs each cycle
    enable_near_resolution: bool = True    # scan near-resolution each cycle
    enable_reviewer: bool = True           # run reviewer at end of each cycle
    # Price range filter: only send "uncertain" markets to GPT.
    price_min: float = 0.10
    price_max: float = 0.90


@dataclass
class NotificationConfig:
    """Telegram notification settings."""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_trades: bool = True
    notify_cycle_summary: bool = True
    notify_errors: bool = True


@dataclass
class Config:
    """Root configuration object."""

    api: APIConfig = field(default_factory=APIConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    claude_analyst: ClaudeAnalystConfig = field(default_factory=ClaudeAnalystConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    alerts: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        """
        Build a Config from defaults → config file → environment variables.
        """
        cfg = cls()
        cfg._apply_file()
        cfg._apply_env()
        return cfg

    def _apply_file(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return

        api = data.get("api", {})
        for key in ("proxy_address", "host", "gamma_host", "data_host"):
            if key in api:
                setattr(self.api, key, api[key])

        trading = data.get("trading", {})
        for key in ("max_per_trade", "max_per_day", "min_shares", "dry_run",
                    "min_roi_threshold"):
            if key in trading:
                setattr(self.trading, key, trading[key])

        monitor = data.get("monitor", {})
        for key in ("watchlist_refresh_interval", "price_history_days",
                    "alert_cooldown_seconds", "max_opportunities",
                    "near_resolution_hours", "near_resolution_min_confidence"):
            if key in monitor:
                setattr(self.monitor, key, monitor[key])

        self.alerts = data.get("alerts", [])

    def _apply_env(self) -> None:
        # Polymarket credentials — env only
        if pk := os.getenv("POLYMARKET_PRIVATE_KEY"):
            self.api.private_key = pk
        if proxy := os.getenv("POLYMARKET_PROXY_ADDRESS"):
            self.api.proxy_address = proxy

        # L2 CLOB API credentials — env only
        if v := os.getenv("POLY_API_KEY"):
            self.api.clob_api_key = v
        if v := os.getenv("POLY_SECRET"):
            self.api.clob_api_secret = v
        if v := os.getenv("POLY_PASSPHRASE"):
            self.api.clob_api_passphrase = v

        # Trading limits
        if v := os.getenv("POLYMARKET_MAX_PER_TRADE"):
            self.trading.max_per_trade = float(v)
        if v := os.getenv("POLYMARKET_MAX_PER_DAY"):
            self.trading.max_per_day = float(v)
        if v := os.getenv("POLYMARKET_DRY_RUN"):
            self.trading.dry_run = v.lower() not in ("false", "0", "no")

        # Anthropic Claude — env only
        if v := os.getenv("ANTHROPIC_API_KEY"):
            self.claude_analyst.api_key = v
        if v := os.getenv("CLAUDE_MODEL"):
            self.claude_analyst.model = v

        # Telegram — env only
        if v := os.getenv("TELEGRAM_BOT_TOKEN"):
            self.notifications.telegram_bot_token = v
        if v := os.getenv("TELEGRAM_CHAT_ID"):
            self.notifications.telegram_chat_id = v

        # Agent
        if v := os.getenv("AGENT_SCAN_INTERVAL"):
            self.agent.scan_interval_seconds = int(v)
        if v := os.getenv("AGENT_DRY_RUN"):
            self.trading.dry_run = v.lower() not in ("false", "0", "no")

    def save_non_sensitive(self) -> None:
        """
        Persist non-sensitive config to ~/.polymarket/config.json.
        Private keys are NEVER written here.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "api": {
                "proxy_address": self.api.proxy_address,
                "host": self.api.host,
                "gamma_host": self.api.gamma_host,
                "data_host": self.api.data_host,
            },
            "trading": {
                "max_per_trade": self.trading.max_per_trade,
                "max_per_day": self.trading.max_per_day,
                "min_shares": self.trading.min_shares,
                "dry_run": self.trading.dry_run,
                "min_roi_threshold": self.trading.min_roi_threshold,
            },
            "monitor": {
                "watchlist_refresh_interval": self.monitor.watchlist_refresh_interval,
                "near_resolution_hours": self.monitor.near_resolution_hours,
                "near_resolution_min_confidence": self.monitor.near_resolution_min_confidence,
                "max_opportunities": self.monitor.max_opportunities,
            },
            "alerts": self.alerts,
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @property
    def has_trading_credentials(self) -> bool:
        return bool(self.api.private_key and self.api.proxy_address)

    @property
    def has_clob_auth(self) -> bool:
        """True if L2 CLOB API credentials are available for authenticated endpoints."""
        return bool(
            self.api.clob_api_key
            and self.api.clob_api_secret
            and self.api.clob_api_passphrase
        )

    @property
    def has_claude_analyst(self) -> bool:
        return bool(self.claude_analyst.api_key)

    @property
    def has_telegram(self) -> bool:
        return bool(
            self.notifications.telegram_bot_token
            and self.notifications.telegram_chat_id
        )
