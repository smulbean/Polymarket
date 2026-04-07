# Polymarket System — Usage Guide

How to run every part of this system, from market scanning to the autonomous background agent.

---

## Prerequisites

1. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

2. Set up credentials (see `CREDENTIALS.md`):
   ```bash
   # Minimum for scanning (no trading):
   ANTHROPIC_API_KEY=sk-ant-...   # optional — only for Claude analysis

   # For live trading, also set:
   POLYMARKET_PRIVATE_KEY=0x...
   POLYMARKET_PROXY_ADDRESS=0x...
   POLYMARKET_DRY_RUN=false
   ```

3. Run tests to verify everything works:
   ```bash
   python3 -m pytest tests/ -q
   # Should print: 252 passed
   ```

---

## The Three Polymarket APIs (Quick Reference)

| API | URL | Auth | What it's for |
|-----|-----|------|---------------|
| Gamma | `https://gamma-api.polymarket.com` | None | Market discovery, metadata, events |
| Data | `https://data-api.polymarket.com` | None | Positions, trades, leaderboards |
| CLOB | `https://clob.polymarket.com` | None (read) / Key (write) | Prices, orderbooks, placing orders |

---

## Command-Line Interface

All commands are accessed through:
```bash
python3 -m cli.main [command]
# or if installed as a package:
polymarket-sdk [command]
```

---

## 1. Market Scanning (No Credentials Needed)

### Bracket / Ladder Arbitrage

Finds markets where a higher price threshold is priced *above* a lower one (monotonicity violation).

```bash
# Scan and display violations
python3 -m cli.main monitor scan

# Scan more markets
python3 -m cli.main monitor scan --limit 500

# Output raw JSON
python3 -m cli.main monitor scan --json
```

**What it finds:** e.g. "Will BTC exceed $70k?" is priced at 65c, but "Will BTC exceed $72k?" is priced at 71c — the higher target should cost *less*, not more.

---

### NegRisk Arbitrage

Finds multi-outcome markets where YES prices don't sum to 1.0.

```bash
# Scan
python3 -m cli.main monitor negrisk

# With tighter filter (only show gaps > 3c per set)
python3 -m cli.main monitor negrisk --min-gap 0.03

# Execute the top opportunity (dry run by default)
python3 -m cli.main monitor negrisk --execute

# Execute and buy 3 sets
python3 -m cli.main monitor negrisk --execute --sets 3
```

**What it finds:** e.g. in a governor race with 3 candidates, YES prices sum to 0.94 — buying all three guarantees $1.00 payout for $0.94 cost.

---

### Near-Resolution Opportunities

Finds markets resolving within N hours where one outcome is near-certain.

```bash
# Default: resolving within 24 hours, 90% minimum confidence
python3 -m cli.main monitor opportunities

# Wider window
python3 -m cli.main monitor opportunities --hours 48

# Stricter confidence
python3 -m cli.main monitor opportunities --confidence 0.95

# JSON output
python3 -m cli.main monitor opportunities --json
```

---

## 2. Running the Full Monitor

Runs one complete monitoring cycle: fetches watchlist prices, calculates P&L on open positions, and surfaces opportunities.

```bash
python3 -m cli.main monitor run

# With a specific wallet address for position tracking
python3 -m cli.main monitor run --wallet 0xYourProxyAddress
```

---

## 3. Trade Log

```bash
# Show all trades
python3 -m cli.main monitor trades

# Filter by status
python3 -m cli.main monitor trades --status open
python3 -m cli.main monitor trades --status won
python3 -m cli.main monitor trades --status lost

# Filter by strategy
python3 -m cli.main monitor trades --strategy negrisk_arb
python3 -m cli.main monitor trades --strategy conviction

# Live trades only (exclude dry runs)
python3 -m cli.main monitor trades --live-only

# JSON
python3 -m cli.main monitor trades --json
```

---

## 4. Learning Loop / Reviewer

Checks whether open trades have resolved, marks them won/lost, scores each strategy, and writes lessons to memory.

```bash
python3 -m cli.main monitor review
```

Output includes a scorecard like:
```
=== TRADE SCORECARD ===
negrisk_arb    W:5  L:0  ROI: 4.2%   P&L: +$8.40
near_resolution W:3  L:1  ROI: 2.1%   P&L: +$3.10
conviction      W:1  L:2  ROI: -8.0%  P&L: -$9.00
```

---

## 5. Configuration

```bash
# Show current config
python3 -m cli.main monitor config

# Enable live trading
python3 -m cli.main monitor config --live

# Revert to dry run
python3 -m cli.main monitor config --dry-run

# Change per-trade limit
python3 -m cli.main monitor config --max-per-trade 15.0

# Change daily limit
python3 -m cli.main monitor config --max-per-day 30.0

# Set wallet address
python3 -m cli.main monitor config --wallet 0xYourProxy
```

Config is persisted to `~/.polymarket/config.json`. Sensitive values (private key, API keys) are never saved to disk — they must come from env vars.

---

## 6. Autonomous Background Agent

The agent runs continuously, scanning every 5 minutes and trading automatically.

### Priority order each cycle:
1. **NegRisk arbs** — guaranteed edge, executed immediately
2. **Near-resolution** — near-certain outcomes resolving soon
3. **Claude analysis** — uncertain markets sent to `claude-opus-4-6` for assessment

### Start / Stop / Status

```bash
# Start in the background (daemon)
python3 -m cli.main monitor agent start

# Start in the foreground (see logs in terminal)
python3 -m cli.main monitor agent start --foreground

# Check if running
python3 -m cli.main monitor agent status

# Stop
python3 -m cli.main monitor agent stop

# Run exactly one cycle (useful for testing)
python3 -m cli.main monitor agent run-once
```

Logs are written to `~/.polymarket/agent.log`.

### What the Agent Does Each Cycle

```
Every 5 minutes:
  1. Fetch up to 200 active markets (min liquidity: $10k, resolving within 7 days)
  2. NegRisk scan → execute arbs within guardrails
  3. Near-resolution scan → execute high-confidence trades
  4. Filter markets with 10–90% YES price → send top 8 to Claude
  5. Execute Claude-recommended trades (BUY_YES or BUY_NO only if edge ≥ 8%)
  6. Run reviewer (check open trades for resolution)
  7. Send Telegram summary
  8. Sleep 5 minutes
```

### Guardrails (always enforced, even in live mode)

| Guardrail | Default | Env Var |
|-----------|---------|---------|
| Dry run mode | `true` | `POLYMARKET_DRY_RUN` |
| Max per trade | $20.00 | `POLYMARKET_MAX_PER_TRADE` |
| Max per day | $50.00 | `POLYMARKET_MAX_PER_DAY` |
| Min order size | 5 shares | — |

---

## 7. Using the Python SDK Directly

```python
from monitor.config import Config
from monitor.backend import PolymarketBackend
from monitor.negrisk import scan_negrisk_arbitrage
from monitor.opportunities import find_near_resolution_opportunities
from monitor.analyst import MarketAnalyst

cfg = Config.load()
backend = PolymarketBackend(cfg)

# Fetch markets
markets = backend.list_markets(limit=200)

# NegRisk scan
from monitor.negrisk import scan_negrisk_arbitrage
opps = scan_negrisk_arbitrage(markets)
for opp in opps:
    print(f"{opp.group_label}: {opp.roi*100:.1f}% ROI")

# Near-resolution
from monitor.opportunities import find_near_resolution_opportunities
opps = find_near_resolution_opportunities(markets, hours_window=24, min_confidence=0.90)

# Claude analysis (requires ANTHROPIC_API_KEY)
analyst = MarketAnalyst.from_config(cfg)
result = analyst.analyse(markets[0])
if result and result.is_actionable():
    print(result.recommendation, result.edge, result.reasoning)
```

---

## 8. Placing a Manual Trade

Trades are always dry-run by default. To place a real order:

```python
from monitor.config import Config
from monitor.backend import PolymarketBackend
from monitor.executor import Executor

cfg = Config.load()
# cfg.trading.dry_run is True by default
# To trade live: cfg.trading.dry_run = False  (or set POLYMARKET_DRY_RUN=false)

executor = Executor(cfg)

trade = executor.execute(
    token_id="<yes_token_id>",   # from market.yes_token_id
    outcome="YES",
    side="buy",
    price=0.65,                  # limit price
    size=10.0,                   # shares (min 5)
    market_id="<market_id>",
    market_question="Will BTC exceed $100k by end of 2025?",
    strategy="manual",
)
print(trade.trade_id, trade.status, trade.cost)
```

---

## 9. Polymarket API Direct Usage

### Gamma API — Get Markets

```python
import requests

# List active markets
r = requests.get("https://gamma-api.polymarket.com/markets", params={
    "active": True,
    "closed": False,
    "limit": 50,
})
markets = r.json()

# Get a specific market by slug
r = requests.get("https://gamma-api.polymarket.com/markets", params={
    "slug": "will-btc-exceed-100k-by-end-of-2025"
})
```

### CLOB API — Get Prices

```python
# Best price for a token
r = requests.get("https://clob.polymarket.com/price", params={
    "token_id": "<yes_token_id>",
    "side": "BUY",
})
price = r.json()["price"]

# Midpoint (between best bid and ask)
r = requests.get("https://clob.polymarket.com/midpoint", params={
    "token_id": "<yes_token_id>",
})
mid = r.json()["mid"]

# Full orderbook
r = requests.get("https://clob.polymarket.com/book", params={
    "token_id": "<yes_token_id>",
})
book = r.json()  # {"bids": [...], "asks": [...]}
```

### Data API — Get Positions

```python
# Public — no auth needed
r = requests.get("https://data-api.polymarket.com/positions", params={
    "user": "0xYourProxyAddress",
})
positions = r.json()
```

---

## 10. Error Reference

| HTTP Code | Cause | Fix |
|-----------|-------|-----|
| 400 | Bad request parameters | Check token_id format, side value, price range |
| 401 | Invalid auth headers | Re-generate API credentials, check signature |
| 404 | Market not found | Confirm condition_id / token_id from Gamma API |
| 425 | Engine restarting | Retry with exponential backoff |
| 429 | Rate limited | Back off and retry |
| 503 | Trading paused | Check polymarket.com status page |

---

## 11. File Locations

| File | Purpose |
|------|---------|
| `~/.polymarket/config.json` | Non-sensitive config (trading limits, watchlist) |
| `~/.polymarket/trades.jsonl` | Full trade history |
| `~/.polymarket/snapshots.jsonl` | Market snapshot history |
| `~/.polymarket/lessons.jsonl` | Extracted strategy lessons |
| `~/.polymarket/prices/<market_id>.jsonl` | Per-market price history |
| `~/.polymarket/agent.pid` | Background agent PID |
| `~/.polymarket/agent.log` | Background agent logs |

---

## 12. Fee Structure

Fees use the formula: `fee = shares × feeRate × price × (1 - price)`

| Market type | Taker fee | Maker rebate |
|-------------|-----------|--------------|
| Crypto | 0.072 | 20% |
| Sports | 0.03 | 25% |
| Politics / Finance / Tech | 0.04 | 25% |
| Other | 0.05 | 25% |
| Geopolitics | 0 | — |

- **Makers pay zero fees** (and earn rebates). Post-only orders are always maker.
- Fees peak at 50% probability and decrease toward 0% and 100%.
- The executor's `min_roi_threshold` (default 5%) accounts for fees automatically.
