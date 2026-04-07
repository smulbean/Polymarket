# Polymarket Credentials & API Keys

Everything you need to set before running the system. Copy these into a `.env` file in the project root.

---

## Quick Setup

```bash
# Create .env in project root
cp .env.example .env   # or create it manually
# Then fill in the values below
```

---

## Required: Wallet (for Live Trading)

These are only needed if you want to place real orders. For market scanning and analysis, they are optional.

| Env Var | Description | How to Get |
|---|---|---|
| `POLYMARKET_PRIVATE_KEY` | Your Polygon/Ethereum wallet private key (hex, `0x...`) | Export from MetaMask, Rabby, or any Ethereum wallet |
| `POLYMARKET_PROXY_ADDRESS` | Your Polymarket proxy wallet address | Log into polymarket.com, connect wallet — your proxy is auto-deployed |

> **What is the proxy address?**
> When you first use polymarket.com, it auto-deploys a proxy contract (Gnosis Safe) tied to your wallet. All orders are signed as `signature_type=2` (GNOSIS_SAFE). Your proxy address appears in the URL when you view your profile: `polymarket.com/profile/0xYOUR_PROXY`.

> **Never commit your private key.** Add `.env` to `.gitignore`.

---

## Required: CLOB API Credentials (for Live Trading)

Polymarket uses a two-tier auth system. Your wallet signs once to derive these lighter credentials, which are then used for every order.

| Env Var | Description | How to Get |
|---|---|---|
| `POLY_API_KEY` | Your CLOB API key | Run `python scripts/generate_api_creds.py` (see below) |
| `POLY_SECRET` | HMAC signing secret | Generated alongside API key |
| `POLY_PASSPHRASE` | API passphrase | Generated alongside API key |

> **Note:** These are NOT currently used by the existing monitor code (which uses `eth_account` direct EIP-712 signing). They are the credentials if you switch to the official `py-clob-client` SDK.

### Generating API Credentials

```python
# scripts/generate_api_creds.py
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key="YOUR_PRIVATE_KEY",  # L1 wallet key
)
creds = client.create_or_derive_api_creds()
print("POLY_API_KEY =", creds.api_key)
print("POLY_SECRET =", creds.api_secret)
print("POLY_PASSPHRASE =", creds.api_passphrase)
```

---

## Required: Anthropic Claude (for Market Analysis)

The agent uses `claude-opus-4-6` to analyse uncertain markets.

| Env Var | Description | How to Get |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key (`sk-ant-...`) | console.anthropic.com → API Keys |

Optional overrides:
```
CLAUDE_MODEL=claude-opus-4-6    # default, change to claude-sonnet-4-6 to reduce cost
```

---

## Optional: Telegram Notifications

The agent sends trade alerts and cycle summaries to a Telegram chat.

| Env Var | Description | How to Get |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token (`123456:ABC-DEF...`) | Message @BotFather on Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Your chat or channel ID | Message @userinfobot, or use `getUpdates` after sending a message to your bot |

### Getting Your Chat ID

1. Start your bot (send any message to it)
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat": {"id": 123456789}` in the response
4. Set `TELEGRAM_CHAT_ID=123456789`

---

## Optional: Trading Limits

Safety guardrails — defaults are conservative.

| Env Var | Default | Description |
|---|---|---|
| `POLYMARKET_DRY_RUN` | `true` | Set to `false` to enable real trades |
| `POLYMARKET_MAX_PER_TRADE` | `20.0` | Max USD per single trade |
| `POLYMARKET_MAX_PER_DAY` | `50.0` | Max USD across all trades per day |

> **`dry_run` is always `true` by default.** You must explicitly set `POLYMARKET_DRY_RUN=false` to place real orders.

---

## Optional: Agent Tuning

| Env Var | Default | Description |
|---|---|---|
| `AGENT_SCAN_INTERVAL` | `300` | Seconds between scan cycles (5 min) |
| `AGENT_DRY_RUN` | inherits `POLYMARKET_DRY_RUN` | Override dry_run for the agent specifically |

---

## Complete `.env` Template

```bash
# ============================================================
# Polymarket Credentials
# ============================================================

# Wallet (required for live trading)
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_PROXY_ADDRESS=0x...

# CLOB API credentials (alternative auth method)
POLY_API_KEY=
POLY_SECRET=
POLY_PASSPHRASE=

# ============================================================
# AI Analysis
# ============================================================
ANTHROPIC_API_KEY=sk-ant-...

# ============================================================
# Telegram Notifications (optional)
# ============================================================
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ============================================================
# Trading Guardrails
# ============================================================
POLYMARKET_DRY_RUN=true       # Change to false for live trading
POLYMARKET_MAX_PER_TRADE=20.0
POLYMARKET_MAX_PER_DAY=50.0

# ============================================================
# Agent Settings
# ============================================================
AGENT_SCAN_INTERVAL=300
```

---

## What Does NOT Require Credentials

The following work with zero setup — no keys needed:

- Browsing markets (Gamma API) — `https://gamma-api.polymarket.com`
- Viewing prices and orderbooks (CLOB public endpoints) — `https://clob.polymarket.com`
- Viewing positions and history (Data API) — `https://data-api.polymarket.com`

The scanner commands (`monitor scan`, `monitor negrisk`, `monitor opportunities`) all use public APIs only.

---

## Blockchain Info

| Property | Value |
|---|---|
| Network | Polygon Mainnet |
| Chain ID | 137 |
| Collateral token | USDC.e (`0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`) |
| Gas token | POL (formerly MATIC) |
| Exchange contract | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` |
| NegRisk Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` |

You need a small amount of POL in your wallet for gas, plus USDC.e to use as collateral.
