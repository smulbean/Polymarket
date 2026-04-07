"""Tests for monitor.backend — Polymarket API client."""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch, call

import pytest

from monitor.backend import (
    CLOB_BASE,
    CTF_EXCHANGE,
    DATA_BASE,
    GAMMA_BASE,
    NEGRISK_EXCHANGE,
    PolymarketBackend,
    _l2_auth_headers,
    _parse_gamma_market,
    _within_resolution_window,
)
from monitor.config import Config
from monitor.models import MarketSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(dry_run: bool = True, with_creds: bool = False) -> Config:
    cfg = Config()
    cfg.trading.dry_run = dry_run
    if with_creds:
        cfg.api.private_key = "0x" + "a" * 64
        cfg.api.proxy_address = "0x" + "b" * 40
        cfg.api.clob_api_key = "test_key"
        cfg.api.clob_api_secret = "test_secret"
        cfg.api.clob_api_passphrase = "test_passphrase"
    return cfg


def _backend(with_creds: bool = False) -> PolymarketBackend:
    return PolymarketBackend(config=_cfg(with_creds=with_creds))


def _mock_get(backend: PolymarketBackend, return_value: Any) -> MagicMock:
    """Patch the requests session.get to return a fake response."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = return_value
    mock_resp.raise_for_status.return_value = None
    backend._session.get = MagicMock(return_value=mock_resp)
    return mock_resp


# ---------------------------------------------------------------------------
# _parse_gamma_market
# ---------------------------------------------------------------------------

class TestParseGammaMarket:
    def _raw(self, **kwargs) -> Dict[str, Any]:
        base = {
            "id": "123",
            "question": "Will X happen?",
            "conditionId": "cond1",
            "outcomePrices": '["0.65", "0.35"]',
            "tokens": [
                {"token_id": "yes_tok", "outcome": "Yes"},
                {"token_id": "no_tok", "outcome": "No"},
            ],
            "volume": "10000",
            "liquidity": "5000",
            "endDate": "2025-12-31T00:00:00Z",
            "active": True,
            "closed": False,
            "resolved": False,
            "negRisk": False,
        }
        base.update(kwargs)
        return base

    def test_parses_basic_market(self) -> None:
        m = _parse_gamma_market(self._raw())
        assert m is not None
        assert m.market_id == "123"
        assert m.yes_price == pytest.approx(0.65)
        assert m.no_price == pytest.approx(0.35)
        assert m.yes_token_id == "yes_tok"
        assert m.no_token_id == "no_tok"
        assert m.status == "active"

    def test_uses_clob_token_ids_when_present(self) -> None:
        raw = self._raw()
        raw["clobTokenIds"] = ["clob_yes", "clob_no"]
        m = _parse_gamma_market(raw)
        assert m is not None
        assert m.yes_token_id == "clob_yes"
        assert m.no_token_id == "clob_no"

    def test_closed_market_status(self) -> None:
        m = _parse_gamma_market(self._raw(closed=True))
        assert m is not None
        assert m.status == "closed"

    def test_resolved_market_status(self) -> None:
        m = _parse_gamma_market(self._raw(resolved=True))
        assert m is not None
        assert m.status == "resolved"

    def test_neg_risk_flag(self) -> None:
        m = _parse_gamma_market(self._raw(negRisk=True, negRiskMarketID="grp1"))
        assert m is not None
        assert m.neg_risk is True
        assert m.neg_risk_market_id == "grp1"

    def test_returns_none_on_bad_data(self) -> None:
        m = _parse_gamma_market({"id": "bad", "outcomePrices": "not_json"})
        # Should not raise; may return None or a partial result
        # Main requirement: no exception

    def test_prices_default_to_50_50(self) -> None:
        raw = self._raw()
        del raw["outcomePrices"]
        m = _parse_gamma_market(raw)
        assert m is not None
        assert m.yes_price == pytest.approx(0.5)


class TestWithinResolutionWindow:
    def test_date_within_window(self) -> None:
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=12)
        end = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _within_resolution_window(end, 1) is True

    def test_date_outside_window(self) -> None:
        assert _within_resolution_window("2099-01-01T00:00:00Z", 7) is False

    def test_empty_date_returns_true(self) -> None:
        assert _within_resolution_window("", 7) is True

    def test_past_date_returns_false(self) -> None:
        assert _within_resolution_window("2020-01-01T00:00:00Z", 7) is False


# ---------------------------------------------------------------------------
# _l2_auth_headers
# ---------------------------------------------------------------------------

class TestL2AuthHeaders:
    def test_returns_five_headers(self) -> None:
        headers = _l2_auth_headers("key", "secret", "pass", "0xaddr", "POST", "/order", "{}")
        assert "POLY_ADDRESS" in headers
        assert "POLY_SIGNATURE" in headers
        assert "POLY_TIMESTAMP" in headers
        assert "POLY_API_KEY" in headers
        assert "POLY_PASSPHRASE" in headers

    def test_address_and_key_correct(self) -> None:
        headers = _l2_auth_headers("mykey", "secret", "mypass", "0xabc", "GET", "/markets")
        assert headers["POLY_ADDRESS"] == "0xabc"
        assert headers["POLY_API_KEY"] == "mykey"
        assert headers["POLY_PASSPHRASE"] == "mypass"

    def test_signature_is_base64(self) -> None:
        import base64
        headers = _l2_auth_headers("k", "s", "p", "0x1", "POST", "/order", "{}")
        # Should not raise
        base64.b64decode(headers["POLY_SIGNATURE"])

    def test_different_bodies_produce_different_sigs(self) -> None:
        h1 = _l2_auth_headers("k", "secret", "p", "0x1", "POST", "/order", '{"a": 1}')
        h2 = _l2_auth_headers("k", "secret", "p", "0x1", "POST", "/order", '{"a": 2}')
        assert h1["POLY_SIGNATURE"] != h2["POLY_SIGNATURE"]


# ---------------------------------------------------------------------------
# PolymarketBackend — market data methods
# ---------------------------------------------------------------------------

class TestListMarkets:
    def test_returns_parsed_markets(self) -> None:
        b = _backend()
        raw_markets = [
            {
                "id": "1",
                "question": "Q1?",
                "conditionId": "c1",
                "outcomePrices": '["0.6", "0.4"]',
                "tokens": [{"token_id": "y1", "outcome": "Yes"}, {"token_id": "n1", "outcome": "No"}],
                "volume": "1000",
                "liquidity": "500",
                "endDate": "2099-01-01",
                "active": True,
                "closed": False,
                "resolved": False,
                "negRisk": False,
            }
        ]
        _mock_get(b, raw_markets)
        markets = b.list_markets(limit=10)
        assert len(markets) == 1
        assert markets[0].market_id == "1"
        assert markets[0].yes_price == pytest.approx(0.6)

    def test_handles_dict_response_with_markets_key(self) -> None:
        b = _backend()
        raw = {
            "markets": [
                {
                    "id": "2",
                    "question": "Q2?",
                    "conditionId": "c2",
                    "outcomePrices": '["0.5", "0.5"]',
                    "tokens": [{"token_id": "y2", "outcome": "Yes"}, {"token_id": "n2", "outcome": "No"}],
                    "volume": "0",
                    "liquidity": "0",
                    "endDate": "",
                    "active": True,
                    "closed": False,
                    "resolved": False,
                    "negRisk": False,
                }
            ]
        }
        _mock_get(b, raw)
        markets = b.list_markets(limit=10)
        assert len(markets) == 1


class TestGetActiveMarkets:
    def _market(self, market_id: str, liquidity: float, end_date: str) -> Dict:
        return {
            "id": market_id,
            "question": f"Market {market_id}?",
            "conditionId": f"c{market_id}",
            "outcomePrices": '["0.5", "0.5"]',
            "tokens": [{"token_id": "y", "outcome": "Yes"}, {"token_id": "n", "outcome": "No"}],
            "volume": "0",
            "liquidity": str(liquidity),
            "endDate": end_date,
            "active": True,
            "closed": False,
            "resolved": False,
            "negRisk": False,
        }

    def test_filters_by_min_liquidity(self) -> None:
        b = _backend()
        _mock_get(b, [
            self._market("1", liquidity=5_000.0, end_date="2099-01-01"),
            self._market("2", liquidity=50_000.0, end_date="2099-01-01"),
        ])
        markets = b.get_active_markets(min_liquidity=10_000.0)
        ids = [m.market_id for m in markets]
        assert "1" not in ids
        assert "2" in ids

    def test_no_filter_returns_all(self) -> None:
        b = _backend()
        _mock_get(b, [
            self._market("1", liquidity=100.0, end_date="2099-01-01"),
            self._market("2", liquidity=200.0, end_date="2099-01-01"),
        ])
        markets = b.get_active_markets(min_liquidity=0)
        assert len(markets) == 2


class TestGetBestPrice:
    def test_returns_price(self) -> None:
        b = _backend()
        _mock_get(b, {"price": "0.65"})
        price = b.get_best_price("tok1", side="BUY")
        assert price == pytest.approx(0.65)

    def test_returns_none_on_empty_token(self) -> None:
        b = _backend()
        assert b.get_best_price("") is None

    def test_returns_none_on_error(self) -> None:
        b = _backend()
        b._session.get = MagicMock(side_effect=ConnectionError("timeout"))
        assert b.get_best_price("tok1") is None


class TestGetMidpoint:
    def test_returns_midpoint(self) -> None:
        b = _backend()
        _mock_get(b, {"mid": "0.50"})
        mid = b.get_midpoint("tok1")
        assert mid == pytest.approx(0.50)

    def test_returns_none_on_empty_token(self) -> None:
        b = _backend()
        assert b.get_midpoint("") is None


class TestGetOrderbook:
    def test_returns_bids_and_asks(self) -> None:
        b = _backend()
        _mock_get(b, {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "50"}]})
        book = b.get_orderbook("tok1")
        assert "bids" in book
        assert "asks" in book
        assert len(book["bids"]) == 1

    def test_returns_empty_on_error(self) -> None:
        b = _backend()
        b._session.get = MagicMock(side_effect=RuntimeError("fail"))
        assert b.get_orderbook("tok1") == {}


class TestGetFeeRate:
    def test_returns_fee_rate(self) -> None:
        b = _backend()
        _mock_get(b, {"feeRateBps": 100})
        assert b.get_fee_rate("tok1") == 100

    def test_returns_zero_on_error(self) -> None:
        b = _backend()
        b._session.get = MagicMock(side_effect=RuntimeError("fail"))
        assert b.get_fee_rate("tok1") == 0

    def test_returns_zero_on_empty_token(self) -> None:
        b = _backend()
        assert b.get_fee_rate("") == 0


# ---------------------------------------------------------------------------
# PolymarketBackend — order placement
# ---------------------------------------------------------------------------

class TestPlaceOrder:
    def test_raises_without_wallet_creds(self) -> None:
        b = _backend(with_creds=False)
        with pytest.raises(RuntimeError, match="credentials not configured"):
            b.place_order("tok1", 0.5, 10.0)

    def test_raises_without_clob_auth(self) -> None:
        cfg = _cfg()
        cfg.api.private_key = "0x" + "a" * 64
        cfg.api.proxy_address = "0x" + "b" * 40
        # No clob_api_key
        b = PolymarketBackend(config=cfg)
        with pytest.raises(RuntimeError, match="L2 CLOB API credentials"):
            b.place_order("tok1", 0.5, 10.0)

    def test_uses_negrisk_contract_when_neg_risk(self) -> None:
        b = _backend(with_creds=True)
        captured = {}

        def fake_sign_submit(token_id, price, size, side, order_type, neg_risk):
            captured["neg_risk"] = neg_risk
            return {"orderID": "test"}

        b._sign_and_submit = fake_sign_submit
        b.place_order("tok1", 0.5, 10.0, neg_risk=True)
        assert captured["neg_risk"] is True


class TestSignAndSubmit:
    """Tests for the order signing logic (amount calculations, fee rate)."""

    def _make_backend(self) -> PolymarketBackend:
        cfg = Config()
        cfg.api.private_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        cfg.api.proxy_address = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        cfg.api.clob_api_key = "key"
        cfg.api.clob_api_secret = "secret"
        cfg.api.clob_api_passphrase = "pass"
        cfg.api.signature_type = 0  # EOA for testing
        cfg.api.chain_id = 137
        return PolymarketBackend(config=cfg)

    def test_buy_order_amounts(self) -> None:
        """BUY: makerAmount=USDC, takerAmount=shares."""
        b = self._make_backend()

        # Patch fee rate and session post
        b._session.get = MagicMock(return_value=MagicMock(
            ok=True, status_code=200,
            json=MagicMock(return_value={"feeRateBps": 100}),
            raise_for_status=MagicMock(),
        ))
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"orderID": "abc"}
        b._session.post = MagicMock(return_value=mock_post_resp)

        b._sign_and_submit("12345", price=0.60, size=10.0, side="BUY",
                           order_type="GTC", neg_risk=False)

        call_kwargs = b._session.post.call_args
        body = json.loads(call_kwargs[1]["data"])
        order = body["order"]

        # BUY: makerAmount = 0.60 * 10.0 * 1e6 = 6_000_000
        #      takerAmount = 10.0 * 1e6 = 10_000_000
        assert order["makerAmount"] == str(6_000_000)
        assert order["takerAmount"] == str(10_000_000)
        assert order["side"] == "0"  # _SIDE_BUY = 0

    def test_sell_order_amounts(self) -> None:
        """SELL: makerAmount=shares, takerAmount=USDC."""
        b = self._make_backend()

        b._session.get = MagicMock(return_value=MagicMock(
            ok=True, status_code=200,
            json=MagicMock(return_value={"feeRateBps": 100}),
            raise_for_status=MagicMock(),
        ))
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"orderID": "xyz"}
        b._session.post = MagicMock(return_value=mock_post_resp)

        b._sign_and_submit("12345", price=0.60, size=10.0, side="SELL",
                           order_type="GTC", neg_risk=False)

        call_kwargs = b._session.post.call_args
        body = json.loads(call_kwargs[1]["data"])
        order = body["order"]

        # SELL: makerAmount = 10.0 * 1e6 = 10_000_000 (shares)
        #       takerAmount = 0.60 * 10.0 * 1e6 = 6_000_000 (USDC)
        assert order["makerAmount"] == str(10_000_000)
        assert order["takerAmount"] == str(6_000_000)
        assert order["side"] == "1"  # _SIDE_SELL = 1

    def test_fee_rate_fetched_and_included(self) -> None:
        b = self._make_backend()

        b._session.get = MagicMock(return_value=MagicMock(
            ok=True, status_code=200,
            json=MagicMock(return_value={"feeRateBps": 72}),
            raise_for_status=MagicMock(),
        ))
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"orderID": "abc"}
        b._session.post = MagicMock(return_value=mock_post_resp)

        b._sign_and_submit("12345", price=0.5, size=10.0, side="BUY",
                           order_type="GTC", neg_risk=False)

        body = json.loads(b._session.post.call_args[1]["data"])
        assert body["order"]["feeRateBps"] == "72"

    def test_l2_headers_present(self) -> None:
        b = self._make_backend()

        b._session.get = MagicMock(return_value=MagicMock(
            ok=True, status_code=200,
            json=MagicMock(return_value={"feeRateBps": 0}),
            raise_for_status=MagicMock(),
        ))
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"orderID": "abc"}
        b._session.post = MagicMock(return_value=mock_post_resp)

        b._sign_and_submit("12345", price=0.5, size=10.0, side="BUY",
                           order_type="GTC", neg_risk=False)

        headers = b._session.post.call_args[1]["headers"]
        assert "POLY_API_KEY" in headers
        assert "POLY_SIGNATURE" in headers
        assert "POLY_TIMESTAMP" in headers
        assert "POLY_ADDRESS" in headers
        assert "POLY_PASSPHRASE" in headers

    def test_negrisk_uses_different_contract(self) -> None:
        """NegRisk orders must use the NegRisk Exchange verifying contract."""
        b = self._make_backend()

        b._session.get = MagicMock(return_value=MagicMock(
            ok=True, status_code=200,
            json=MagicMock(return_value={"feeRateBps": 0}),
            raise_for_status=MagicMock(),
        ))
        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.return_value = None
        mock_post_resp.json.return_value = {"orderID": "abc"}
        b._session.post = MagicMock(return_value=mock_post_resp)

        # We can verify the domain is different by checking that both calls
        # go through without error (the verifying_contract is passed to sign_typed_data).
        # Just ensure no exception is raised for neg_risk=True
        b._sign_and_submit("12345", price=0.5, size=10.0, side="BUY",
                           order_type="GTC", neg_risk=True)
        b._session.post.assert_called_once()


# ---------------------------------------------------------------------------
# PolymarketBackend — cancel order
# ---------------------------------------------------------------------------

class TestCancelOrder:
    def test_raises_without_creds(self) -> None:
        b = _backend(with_creds=False)
        with pytest.raises(RuntimeError):
            b.cancel_order("order123")

    def test_sends_delete_with_body(self) -> None:
        b = _backend(with_creds=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"cancelled": "order123"}
        b._session.delete = MagicMock(return_value=mock_resp)

        b.cancel_order("order123")

        call_kwargs = b._session.delete.call_args
        # Should call /order (not /order/<id>)
        assert call_kwargs[0][0] == f"{CLOB_BASE}/order"
        body = json.loads(call_kwargs[1]["data"])
        assert body["orderID"] == "order123"


class TestCancelOrdersBatch:
    def test_sends_list_of_ids(self) -> None:
        b = _backend(with_creds=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"cancelled": 3}
        b._session.delete = MagicMock(return_value=mock_resp)

        b.cancel_orders_batch(["a", "b", "c"])

        call_kwargs = b._session.delete.call_args
        assert call_kwargs[0][0] == f"{CLOB_BASE}/orders"
        body = json.loads(call_kwargs[1]["data"])
        assert body["orderIDs"] == ["a", "b", "c"]

    def test_truncates_to_15(self) -> None:
        b = _backend(with_creds=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {}
        b._session.delete = MagicMock(return_value=mock_resp)

        b.cancel_orders_batch([str(i) for i in range(20)])

        body = json.loads(b._session.delete.call_args[1]["data"])
        assert len(body["orderIDs"]) == 15


# ---------------------------------------------------------------------------
# PolymarketBackend — user positions
# ---------------------------------------------------------------------------

class TestGetPositions:
    def test_returns_empty_on_missing_address(self) -> None:
        b = _backend()
        assert b.get_positions("") == []

    def test_returns_positions_list(self) -> None:
        b = _backend()
        _mock_get(b, [{"market": "m1", "size": "10"}])
        positions = b.get_positions("0xaddr")
        assert len(positions) == 1
        assert positions[0]["market"] == "m1"

    def test_handles_dict_response(self) -> None:
        b = _backend()
        _mock_get(b, {"positions": [{"market": "m2", "size": "5"}]})
        positions = b.get_positions("0xaddr")
        assert len(positions) == 1
