"""
Polymarket HTTP API backend.

Wraps the public Gamma and CLOB REST APIs for reading market data,
and the CLOB trading API (EIP-712 + L2 HMAC auth) for order placement.
All public-data methods work without any credentials.

Data APIs used:
  Gamma  — https://gamma-api.polymarket.com   (market metadata, NegRisk)
  CLOB   — https://clob.polymarket.com        (orderbooks, price history)
  Data   — https://data-api.polymarket.com    (user positions — public!)

Authentication (trading endpoints only):
  Two-tier system:
    L1 — EIP-712 structured-data signature on each order struct
    L2 — HMAC-SHA256 request headers (POLY_ADDRESS, POLY_SIGNATURE,
         POLY_TIMESTAMP, POLY_API_KEY, POLY_PASSPHRASE)

Contract addresses (Polygon mainnet, chain 137):
  CTF Exchange        0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
  NegRisk Exchange    0xC5d563A36AE78145C45a50134d48A1215220f80a
  USDC.e              0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from .config import Config
from .models import MarketSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"

# Polygon mainnet contract addresses
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Token decimals: USDC.e has 6, outcome tokens also use 6 in Polymarket
_USDC_DECIMALS = 1_000_000  # 1e6

_DEFAULT_TIMEOUT = 15
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0

# EIP-712 Order type definition (matches Polymarket Exchange contract ABI)
_ORDER_TYPES = {
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"},
        {"name": "taker", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "expiration", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "feeRateBps", "type": "uint256"},
        {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
    ]
}

# side encoding
_SIDE_BUY = 0
_SIDE_SELL = 1


# ---------------------------------------------------------------------------
# HTTP session helpers
# ---------------------------------------------------------------------------


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "polymarket-monitor/1.0"})
    return s


def _get(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = _MAX_RETRIES,
) -> Any:
    """GET with exponential back-off on rate-limits and transient errors.

    HTTP 425 (engine restarting), 429 (rate limited), 502/503/504 all retry.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
            if resp.status_code in (425, 429, 502, 503, 504):
                delay = _RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Transient HTTP %d from %s — retrying in %.1fs",
                    resp.status_code, url, delay,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(_RETRY_DELAY * (2 ** attempt))
    raise RuntimeError(f"HTTP GET {url} failed after {retries} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# L2 HMAC auth helpers
# ---------------------------------------------------------------------------


def _l2_auth_headers(
    api_key: str,
    secret: str,
    passphrase: str,
    address: str,
    method: str,
    path: str,
    body: str = "",
) -> Dict[str, str]:
    """
    Build the five L2 authentication headers for CLOB trading endpoints.

    Signature: HMAC-SHA256(secret, timestamp + METHOD + path + body)
    Encoded as base64.
    """
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "POLY_ADDRESS": address,
        "POLY_SIGNATURE": sig,
        "POLY_TIMESTAMP": timestamp,
        "POLY_API_KEY": api_key,
        "POLY_PASSPHRASE": passphrase,
    }


# ---------------------------------------------------------------------------
# Gamma-API data parsers
# ---------------------------------------------------------------------------


def _parse_gamma_market(raw: Dict[str, Any]) -> Optional[MarketSnapshot]:
    """Convert a raw Gamma API market dict into a MarketSnapshot.

    The Gamma API uses several field layouts across different endpoints.
    This parser handles both the legacy `tokens[]` array and the newer
    `clobTokenIds` array.
    """
    try:
        # --- Prices ---
        prices_raw = raw.get("outcomePrices", '["0.5", "0.5"]')
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        yes_price = float(prices[0]) if prices else 0.5
        no_price = float(prices[1]) if len(prices) > 1 else round(1.0 - yes_price, 4)

        # --- Token IDs ---
        # Newer Gamma response: clobTokenIds = ["YES_TOKEN_ID", "NO_TOKEN_ID"]
        clob_ids = raw.get("clobTokenIds") or raw.get("clob_token_ids")
        if clob_ids and len(clob_ids) >= 2:
            yes_token = str(clob_ids[0])
            no_token = str(clob_ids[1])
        else:
            # Legacy: tokens = [{token_id, outcome}, ...]
            tokens = raw.get("tokens", [])
            yes_token = next(
                (str(t.get("token_id", t.get("tokenId", "")))
                 for t in tokens
                 if str(t.get("outcome", "")).lower() in ("yes", "1")),
                "",
            )
            no_token = next(
                (str(t.get("token_id", t.get("tokenId", "")))
                 for t in tokens
                 if str(t.get("outcome", "")).lower() in ("no", "0")),
                "",
            )

        # --- Status ---
        status = "active"
        if raw.get("closed"):
            status = "closed"
        elif raw.get("resolved"):
            status = "resolved"

        # --- End date ---
        end_date = raw.get("endDate") or raw.get("end_date_iso") or ""
        # Normalise to ISO-8601 string
        if end_date and not isinstance(end_date, str):
            end_date = str(end_date)

        return MarketSnapshot(
            market_id=str(raw.get("id", "")),
            question=raw.get("question", ""),
            condition_id=raw.get("conditionId", raw.get("condition_id", "")),
            yes_token_id=yes_token,
            no_token_id=no_token,
            yes_price=yes_price,
            no_price=no_price,
            volume=float(raw.get("volume", 0) or 0),
            liquidity=float(raw.get("liquidity", 0) or 0),
            end_date=end_date,
            status=status,
            neg_risk=bool(raw.get("negRisk", raw.get("neg_risk", False))),
            neg_risk_market_id=(
                raw.get("negRiskMarketID")
                or raw.get("negRiskMarketId")
                or raw.get("neg_risk_market_id")
            ),
            group_item_title=raw.get("groupItemTitle", raw.get("group_item_title")),
            event_id=str(raw.get("eventId", raw.get("event_id", ""))) or None,
        )
    except (KeyError, ValueError, json.JSONDecodeError, IndexError) as exc:
        logger.debug("Failed to parse market %s: %s", raw.get("id"), exc)
        return None


def _within_resolution_window(end_date: str, days: int) -> bool:
    """Return True if end_date is within *days* days from now."""
    if not end_date:
        return True  # unknown end date — include by default
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            end = datetime.strptime(end_date, fmt).replace(tzinfo=timezone.utc)
            delta = (end - datetime.now(timezone.utc)).total_seconds()
            return 0 < delta <= days * 86_400
        except ValueError:
            continue
    return True


# ---------------------------------------------------------------------------
# Public backend class
# ---------------------------------------------------------------------------


class PolymarketBackend:
    """
    Thin HTTP client wrapping the public Polymarket APIs.

    All read operations work without credentials.  Order placement and
    cancellation require both:
      - POLYMARKET_PRIVATE_KEY + POLYMARKET_PROXY_ADDRESS  (EIP-712 L1)
      - POLY_API_KEY + POLY_SECRET + POLY_PASSPHRASE       (HMAC L2)
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config.load()
        self._session = _make_session()

    # ------------------------------------------------------------------
    # Market data (Gamma API — no auth)
    # ------------------------------------------------------------------

    def search_markets(
        self,
        query: str,
        limit: int = 50,
        active_only: bool = True,
    ) -> List[MarketSnapshot]:
        """Free-text search across all Polymarket markets."""
        params: Dict[str, Any] = {"limit": limit, "search": query}
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        raw = _get(self._session, f"{GAMMA_BASE}/markets", params)
        if isinstance(raw, dict):
            raw = raw.get("markets", [])
        return [m for m in (_parse_gamma_market(r) for r in raw) if m is not None]

    def list_markets(
        self,
        limit: int = 100,
        active_only: bool = True,
        neg_risk_only: bool = False,
        offset: int = 0,
    ) -> List[MarketSnapshot]:
        """
        List markets with optional filters.

        Handles Gamma API pagination automatically when limit > 100 by
        issuing multiple requests with the ``next_cursor`` / offset.
        """
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"
        if neg_risk_only:
            params["neg_risk"] = "true"
        if offset:
            params["offset"] = offset

        all_markets: List[MarketSnapshot] = []
        fetched = 0

        while fetched < limit:
            params["limit"] = min(100, limit - fetched)
            raw = _get(self._session, f"{GAMMA_BASE}/markets", params)
            page: List[Dict[str, Any]] = []
            if isinstance(raw, dict):
                page = raw.get("markets", [])
                next_cursor = raw.get("next_cursor") or raw.get("nextCursor")
            else:
                page = raw if isinstance(raw, list) else []
                next_cursor = None

            parsed = [m for m in (_parse_gamma_market(r) for r in page) if m is not None]
            all_markets.extend(parsed)
            fetched += len(page)

            if not page or not next_cursor or len(page) < params["limit"]:
                break
            params["next_cursor"] = next_cursor

        return all_markets[:limit]

    def get_market(self, market_id: str) -> Optional[MarketSnapshot]:
        """Fetch a single market by its Gamma ID."""
        raw = _get(self._session, f"{GAMMA_BASE}/markets/{market_id}")
        if not raw:
            return None
        return _parse_gamma_market(raw)

    def get_market_by_condition_id(self, condition_id: str) -> Optional[MarketSnapshot]:
        """Fetch a single market by its on-chain condition ID (CLOB endpoint)."""
        try:
            raw = _get(self._session, f"{CLOB_BASE}/markets/{condition_id}")
            if not raw:
                return None
            # CLOB /markets response uses different field names
            return _parse_gamma_market(raw)
        except Exception as exc:
            logger.debug("get_market_by_condition_id(%s) failed: %s", condition_id, exc)
            return None

    def list_neg_risk_markets(self, limit: int = 500) -> List[MarketSnapshot]:
        """Return all active NegRisk markets."""
        return self.list_markets(limit=limit, active_only=True, neg_risk_only=True)

    def get_active_markets(
        self,
        limit: int = 200,
        min_liquidity: float = 0.0,
        resolution_window_days: int = 0,
    ) -> List[MarketSnapshot]:
        """
        Fetch active markets filtered by liquidity and resolution window.

        Used by the autonomous agent each cycle.

        Parameters
        ----------
        limit:
            Max markets to return (after filtering).
        min_liquidity:
            Skip markets with liquidity below this threshold (USD).
        resolution_window_days:
            If > 0, only return markets resolving within this many days.
            0 means no filter.
        """
        # Fetch a generous batch to account for filtering losses
        fetch_limit = min(limit * 3, 500)
        markets = self.list_markets(limit=fetch_limit, active_only=True)

        if min_liquidity > 0:
            markets = [m for m in markets if m.liquidity >= min_liquidity]
        if resolution_window_days > 0:
            markets = [
                m for m in markets
                if _within_resolution_window(m.end_date, resolution_window_days)
            ]

        return markets[:limit]

    # ------------------------------------------------------------------
    # Price data (CLOB API — no auth)
    # ------------------------------------------------------------------

    def get_best_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """
        Return the best available price for a token on the given side.

        Uses ``GET /price?token_id=...&side=BUY|SELL``.
        The ``side`` must be ``"BUY"`` or ``"SELL"`` (case-insensitive).
        """
        if not token_id:
            return None
        try:
            raw = _get(
                self._session,
                f"{CLOB_BASE}/price",
                {"token_id": token_id, "side": side.upper()},
            )
            return float(raw.get("price", 0)) if raw else None
        except Exception:
            return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Return the current midpoint price for a token (0–1)."""
        if not token_id:
            return None
        try:
            raw = _get(self._session, f"{CLOB_BASE}/midpoint", {"token_id": token_id})
            return float(raw.get("mid", 0))
        except Exception:
            return None

    def get_midpoints_batch(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Fetch midpoints for multiple tokens in one request.

        Uses ``POST /midpoints`` — more efficient than individual calls.
        Returns {token_id: midpoint}.
        """
        if not token_ids:
            return {}
        try:
            resp = self._session.post(
                f"{CLOB_BASE}/midpoints",
                json={"token_ids": token_ids},
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return {k: float(v) for k, v in data.items() if v is not None}
        except Exception as exc:
            logger.warning("Batch midpoint fetch failed: %s", exc)
            return {}

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch the full order book for a token.

        Uses ``GET /book?token_id=...``.
        Returns ``{"bids": [...], "asks": [...]}`` — each entry is
        ``{"price": str, "size": str}``.
        """
        if not token_id:
            return {}
        try:
            return _get(self._session, f"{CLOB_BASE}/book", {"token_id": token_id})
        except Exception as exc:
            logger.warning("get_orderbook(%s) failed: %s", token_id[:20], exc)
            return {}

    def get_spread(self, token_id: str) -> Optional[float]:
        """Return the bid-ask spread for a token."""
        if not token_id:
            return None
        try:
            raw = _get(self._session, f"{CLOB_BASE}/spread", {"token_id": token_id})
            return float(raw.get("spread", 0)) if raw else None
        except Exception:
            return None

    def get_fee_rate(self, token_id: str) -> int:
        """
        Fetch the current fee rate in basis points for a token.

        Uses ``GET /fee-rate?token_id=...``.  Must be included in the
        signed order payload — the exchange rejects orders with wrong rates.
        Returns 0 on error (safe default for post-only / maker orders).
        """
        if not token_id:
            return 0
        try:
            raw = _get(self._session, f"{CLOB_BASE}/fee-rate", {"token_id": token_id})
            return int(raw.get("feeRateBps", 0))
        except Exception as exc:
            logger.warning("get_fee_rate(%s) failed: %s — using 0", token_id[:20], exc)
            return 0

    def get_price_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Fetch OHLC-style price history for a token.

        Parameters
        ----------
        interval:
            One of ``"1m"``, ``"1h"``, ``"6h"``, ``"1d"``, ``"1w"``, ``"max"``.
        fidelity:
            Number of data points to return.
        """
        try:
            raw = _get(
                self._session,
                f"{CLOB_BASE}/prices-history",
                {"market": token_id, "interval": interval, "fidelity": fidelity},
            )
            return raw.get("history", [])
        except Exception:
            return []

    # ------------------------------------------------------------------
    # User positions (Data API — no auth)
    # ------------------------------------------------------------------

    def get_positions(self, wallet_address: str) -> List[Dict[str, Any]]:
        """
        Fetch open positions for a wallet address.

        Uses ``GET /positions?user=<address>`` on the public Data API.
        No authentication required.
        """
        if not wallet_address:
            return []
        try:
            raw = _get(
                self._session,
                f"{DATA_BASE}/positions",
                {"user": wallet_address, "sizeThreshold": "0.01"},
            )
            if isinstance(raw, list):
                return raw
            return raw.get("data", raw.get("positions", []))
        except Exception as exc:
            logger.warning("Failed to fetch positions for %s: %s", wallet_address[:10], exc)
            return []

    def get_trade_history(self, wallet_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch trade history for a wallet address (Data API — no auth).
        """
        if not wallet_address:
            return []
        try:
            raw = _get(
                self._session,
                f"{DATA_BASE}/activity",
                {"user": wallet_address, "limit": limit},
            )
            if isinstance(raw, list):
                return raw
            return raw.get("data", raw.get("history", []))
        except Exception as exc:
            logger.warning("Failed to fetch trade history for %s: %s", wallet_address[:10], exc)
            return []

    # ------------------------------------------------------------------
    # Order placement (requires L1 EIP-712 + L2 HMAC auth)
    # ------------------------------------------------------------------

    def place_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
        order_type: str = "GTC",
        neg_risk: bool = False,
    ) -> Dict[str, Any]:
        """
        Place a limit order on the CLOB.

        Requires:
          - POLYMARKET_PRIVATE_KEY + POLYMARKET_PROXY_ADDRESS  (EIP-712)
          - POLY_API_KEY + POLY_SECRET + POLY_PASSPHRASE       (HMAC headers)

        Parameters
        ----------
        token_id:
            Outcome token to trade (YES or NO ``token_id`` from market data).
        price:
            Limit price in [0.01, 0.99].
        size:
            Number of shares (minimum 5; each share pays $1 if correct).
        side:
            ``"BUY"`` or ``"SELL"``.
        order_type:
            ``"GTC"`` (good-till-cancelled), ``"GTD"``, ``"FOK"``, or ``"FAK"``.
        neg_risk:
            If True, signs against the NegRisk Exchange contract.
        """
        if not self.config.has_trading_credentials:
            raise RuntimeError(
                "Trading credentials not configured.  "
                "Set POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS."
            )
        if not self.config.has_clob_auth:
            raise RuntimeError(
                "L2 CLOB API credentials not configured.  "
                "Set POLY_API_KEY, POLY_SECRET, and POLY_PASSPHRASE.  "
                "See CREDENTIALS.md for how to generate them."
            )
        return self._sign_and_submit(token_id, price, size, side, order_type, neg_risk)

    def _sign_and_submit(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str,
        order_type: str,
        neg_risk: bool = False,
    ) -> Dict[str, Any]:
        """
        Build, EIP-712 sign, and submit a limit order to the CLOB.

        Order amounts (USDC.e has 6 decimal places):
          BUY:  makerAmount = price × size × 1e6  (USDC you spend)
                takerAmount = size × 1e6           (shares you receive)
          SELL: makerAmount = size × 1e6           (shares you spend)
                takerAmount = price × size × 1e6   (USDC you receive)
        """
        from eth_account import Account

        maker = self.config.api.proxy_address
        signer_address = Account.from_key(self.config.api.private_key).address
        private_key = self.config.api.private_key
        verifying_contract = NEGRISK_EXCHANGE if neg_risk else CTF_EXCHANGE
        domain_name = "Neg Risk CTF Exchange" if neg_risk else "CTF Exchange"
        side_int = _SIDE_BUY if side.upper() == "BUY" else _SIDE_SELL

        # Amounts: token amounts use 6 decimals (same as USDC.e)
        if side_int == _SIDE_BUY:
            maker_amount = round(price * size * _USDC_DECIMALS)
            taker_amount = round(size * _USDC_DECIMALS)
        else:
            maker_amount = round(size * _USDC_DECIMALS)
            taker_amount = round(price * size * _USDC_DECIMALS)

        # Fetch real fee rate — required by the exchange; wrong value = rejection
        fee_rate_bps = self.get_fee_rate(token_id)

        salt = random.randint(1, 2 ** 128)  # random uint256 nonce
        expiration = 0  # 0 = GTC (no expiry)
        nonce = 0       # 0 is valid for standard orders

        domain_data = {
            "name": domain_name,
            "version": "1",
            "chainId": self.config.api.chain_id,
            "verifyingContract": verifying_contract,
        }
        message_data = {
            "salt": salt,
            "maker": maker,
            "signer": signer_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": expiration,
            "nonce": nonce,
            "feeRateBps": fee_rate_bps,
            "side": side_int,
            "signatureType": self.config.api.signature_type,
        }

        # EIP-712 structured data signature
        account = Account.from_key(private_key)
        signed = account.sign_typed_data(
            domain_data=domain_data,
            message_types=_ORDER_TYPES,
            message_data=message_data,
        )

        # Order body sent to the exchange
        order_body = {
            "salt": str(salt),
            "maker": maker,
            "signer": signer_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": token_id,
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": str(expiration),
            "nonce": str(nonce),
            "feeRateBps": str(fee_rate_bps),
            "side": str(side_int),
            "signatureType": str(self.config.api.signature_type),
        }
        payload = {
            "order": order_body,
            "signature": signed.signature.hex(),
            "owner": maker,
            "orderType": order_type,
        }
        body_str = json.dumps(payload)

        # L2 HMAC auth headers
        auth_headers = _l2_auth_headers(
            api_key=self.config.api.clob_api_key,
            secret=self.config.api.clob_api_secret,
            passphrase=self.config.api.clob_api_passphrase,
            address=maker,
            method="POST",
            path="/order",
            body=body_str,
        )
        auth_headers["Content-Type"] = "application/json"

        resp = self._session.post(
            f"{CLOB_BASE}/order",
            data=body_str,
            headers=auth_headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an open order by its exchange ID.

        Uses ``DELETE /order`` with body ``{"orderID": "<id>"}`` and
        L2 HMAC auth headers.
        """
        if not self.config.has_trading_credentials:
            raise RuntimeError("Trading credentials not configured.")
        if not self.config.has_clob_auth:
            raise RuntimeError("L2 CLOB API credentials not configured.")

        body_str = json.dumps({"orderID": order_id})
        auth_headers = _l2_auth_headers(
            api_key=self.config.api.clob_api_key,
            secret=self.config.api.clob_api_secret,
            passphrase=self.config.api.clob_api_passphrase,
            address=self.config.api.proxy_address,
            method="DELETE",
            path="/order",
            body=body_str,
        )
        auth_headers["Content-Type"] = "application/json"

        resp = self._session.delete(
            f"{CLOB_BASE}/order",
            data=body_str,
            headers=auth_headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_orders_batch(self, order_ids: List[str]) -> Dict[str, Any]:
        """
        Cancel multiple open orders in a single request (max 15 per batch).

        Uses ``DELETE /orders`` with body ``{"orderIDs": [...]}``.
        """
        if not self.config.has_trading_credentials:
            raise RuntimeError("Trading credentials not configured.")
        if not self.config.has_clob_auth:
            raise RuntimeError("L2 CLOB API credentials not configured.")

        body_str = json.dumps({"orderIDs": order_ids[:15]})
        auth_headers = _l2_auth_headers(
            api_key=self.config.api.clob_api_key,
            secret=self.config.api.clob_api_secret,
            passphrase=self.config.api.clob_api_passphrase,
            address=self.config.api.proxy_address,
            method="DELETE",
            path="/orders",
            body=body_str,
        )
        auth_headers["Content-Type"] = "application/json"

        resp = self._session.delete(
            f"{CLOB_BASE}/orders",
            data=body_str,
            headers=auth_headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
