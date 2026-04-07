"""Tests for monitor.analyst — Claude API market analysis."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from monitor.analyst import AnalysisResult, MarketAnalyst, analyse_market
from monitor.models import MarketSnapshot


def _make_market(
    market_id: str = "m1",
    question: str = "Will BTC exceed $100k?",
    yes_price: float = 0.45,
    no_price: float = 0.55,
) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        question=question,
        condition_id="cond1",
        yes_token_id="yes1",
        no_token_id="no1",
        yes_price=yes_price,
        no_price=no_price,
        volume=50_000.0,
        liquidity=20_000.0,
        end_date="2025-12-31",
        status="active",
    )


class TestAnalysisResult:
    def test_is_actionable_buy_yes(self) -> None:
        r = AnalysisResult(
            probability=0.60,
            edge=0.15,
            recommendation="BUY_YES",
            confidence=0.75,
            reasoning="Strong signal",
        )
        assert r.is_actionable()

    def test_is_not_actionable_hold(self) -> None:
        r = AnalysisResult(
            probability=0.47,
            edge=0.02,
            recommendation="HOLD",
            confidence=0.80,
            reasoning="No edge",
        )
        assert not r.is_actionable()

    def test_is_not_actionable_low_confidence(self) -> None:
        r = AnalysisResult(
            probability=0.60,
            edge=0.15,
            recommendation="BUY_YES",
            confidence=0.40,
            reasoning="Low confidence",
        )
        assert not r.is_actionable()

    def test_to_dict(self) -> None:
        r = AnalysisResult(
            probability=0.60,
            edge=0.15,
            recommendation="BUY_YES",
            confidence=0.75,
            reasoning="Test",
            market_id="m1",
        )
        d = r.to_dict()
        assert d["market_id"] == "m1"
        assert d["recommendation"] == "BUY_YES"


class TestAnalyseMarket:
    def test_returns_none_if_no_api_key(self) -> None:
        market = _make_market()
        result = analyse_market(market, api_key="")
        assert result is None

    def test_returns_none_if_anthropic_not_installed(self) -> None:
        market = _make_market()
        with patch("monitor.analyst._HAVE_ANTHROPIC", False):
            result = analyse_market(market, api_key="sk-test")
        assert result is None

    def test_parses_valid_response(self) -> None:
        market = _make_market()
        response_json = json.dumps({
            "probability": 0.60,
            "edge": 0.15,
            "recommendation": "BUY_YES",
            "confidence": 0.80,
            "reasoning": "Market underpricing the outcome",
        })
        mock_block = MagicMock()
        mock_block.text = response_json
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("monitor.analyst._HAVE_ANTHROPIC", True), \
             patch("monitor.analyst.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            result = analyse_market(market, api_key="sk-test")

        assert result is not None
        assert result.probability == pytest.approx(0.60)
        assert result.recommendation == "BUY_YES"
        assert result.market_id == market.market_id

    def test_handles_json_fence(self) -> None:
        """Claude sometimes wraps JSON in ```json fences."""
        market = _make_market()
        response_json = (
            "```json\n"
            '{"probability": 0.55, "edge": 0.10, "recommendation": "BUY_YES",'
            ' "confidence": 0.70, "reasoning": "test"}\n'
            "```"
        )
        mock_block = MagicMock()
        mock_block.text = response_json
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("monitor.analyst._HAVE_ANTHROPIC", True), \
             patch("monitor.analyst.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            result = analyse_market(market, api_key="sk-test")

        assert result is not None
        assert result.recommendation == "BUY_YES"

    def test_returns_none_on_api_error(self) -> None:
        market = _make_market()
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API timeout")

        with patch("monitor.analyst._HAVE_ANTHROPIC", True), \
             patch("monitor.analyst.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            result = analyse_market(market, api_key="sk-test")

        assert result is None

    def test_returns_none_on_bad_json(self) -> None:
        market = _make_market()
        mock_block = MagicMock()
        mock_block.text = "not valid json at all"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("monitor.analyst._HAVE_ANTHROPIC", True), \
             patch("monitor.analyst.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic.return_value = mock_client
            result = analyse_market(market, api_key="sk-test")

        assert result is None


class TestMarketAnalyst:
    def _make_analyst(self) -> MarketAnalyst:
        return MarketAnalyst(api_key="sk-test", min_edge=0.08, min_confidence=0.65)

    def test_analyse_batch_filters_non_actionable(self) -> None:
        analyst = self._make_analyst()
        markets = [_make_market(market_id=f"m{i}") for i in range(3)]

        # All return HOLD
        with patch.object(analyst, "analyse") as mock_analyse:
            mock_analyse.return_value = AnalysisResult(
                probability=0.47,
                edge=0.02,
                recommendation="HOLD",
                confidence=0.80,
                reasoning="no edge",
            )
            results = analyst.analyse_batch(markets)

        assert results == []

    def test_analyse_batch_respects_max_calls(self) -> None:
        analyst = self._make_analyst()
        markets = [_make_market(market_id=f"m{i}") for i in range(10)]

        call_count = []

        def side_effect(market: MarketSnapshot) -> AnalysisResult:
            call_count.append(1)
            return AnalysisResult(
                probability=0.60,
                edge=0.15,
                recommendation="BUY_YES",
                confidence=0.80,
                reasoning="edge",
                market_id=market.market_id,
            )

        with patch.object(analyst, "analyse", side_effect=side_effect):
            analyst.analyse_batch(markets, max_calls=4)

        assert len(call_count) == 4

    def test_from_config(self) -> None:
        from monitor.config import Config
        cfg = Config()
        cfg.claude_analyst.api_key = "sk-abc"
        cfg.claude_analyst.model = "claude-opus-4-6"
        analyst = MarketAnalyst.from_config(cfg)
        assert analyst._api_key == "sk-abc"
        assert analyst._model == "claude-opus-4-6"
