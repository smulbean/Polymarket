"""
Claude-powered market analyst.

Uses the Anthropic Claude API (claude-opus-4-6) to assess whether a
Polymarket prediction market's current YES price is mispriced.

Returns a structured AnalysisResult with probability estimate, edge,
recommendation, confidence, and brief reasoning.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

try:
    import anthropic
    from pydantic import BaseModel, Field, ValidationError
    _HAVE_ANTHROPIC = True
except ImportError:
    _HAVE_ANTHROPIC = False

from .models import MarketSnapshot

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a quantitative analyst specialising in prediction markets.
Given a Polymarket market's metadata and current prices, assess whether
the YES price is fair.

Respond ONLY with valid JSON matching this schema:
{
  "probability": <float 0-1, your estimate of the true YES probability>,
  "edge": <float, your_prob - market_yes_price (positive = market underpriced)>,
  "recommendation": <"BUY_YES" | "BUY_NO" | "HOLD">,
  "confidence": <float 0-1, how confident you are in this assessment>,
  "reasoning": <string, 1-3 sentences>
}

Rules:
- Only recommend BUY_YES if edge > 0.08 and confidence > 0.65
- Only recommend BUY_NO if edge < -0.08 and confidence > 0.65
- Otherwise recommend HOLD
- Be conservative: prediction markets are often efficient
"""


class AnalysisResult:
    """Structured output from Claude market analysis."""

    __slots__ = (
        "probability", "edge", "recommendation",
        "confidence", "reasoning", "market_id",
    )

    def __init__(
        self,
        probability: float,
        edge: float,
        recommendation: str,
        confidence: float,
        reasoning: str,
        market_id: str = "",
    ) -> None:
        self.probability = probability
        self.edge = edge
        self.recommendation = recommendation
        self.confidence = confidence
        self.reasoning = reasoning
        self.market_id = market_id

    def is_actionable(self, min_edge: float = 0.08, min_confidence: float = 0.65) -> bool:
        return (
            self.recommendation in ("BUY_YES", "BUY_NO")
            and abs(self.edge) >= min_edge
            and self.confidence >= min_confidence
        )

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "probability": self.probability,
            "edge": self.edge,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


def _build_market_payload(market: MarketSnapshot) -> str:
    payload = {
        "question": market.question,
        "market_id": market.market_id,
        "yes_price": market.yes_price,
        "no_price": market.no_price,
        "volume": market.volume,
        "status": market.status,
    }
    if market.end_date:
        payload["end_date"] = market.end_date
    return json.dumps(payload, indent=2)


def analyse_market(
    market: MarketSnapshot,
    api_key: str,
    model: str = "claude-opus-4-6",
    max_tokens: int = 1024,
    min_edge: float = 0.08,
    min_confidence: float = 0.65,
) -> Optional[AnalysisResult]:
    """
    Ask Claude to analyse a single market.

    Returns None if the API is unavailable, the key is missing, or the
    response cannot be parsed.
    """
    if not _HAVE_ANTHROPIC:
        logger.warning("anthropic package not installed — skipping analysis")
        return None
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping analysis")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_market_payload(market)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.error("Claude API call failed for %s: %s", market.market_id, exc)
        return None

    # Extract the text block (skip thinking blocks)
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text = block.text
            break

    if not text:
        logger.warning("No text in Claude response for %s", market.market_id)
        return None

    # Parse JSON response
    # Claude may wrap it in ```json fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
        result = AnalysisResult(
            probability=float(data["probability"]),
            edge=float(data["edge"]),
            recommendation=str(data["recommendation"]),
            confidence=float(data["confidence"]),
            reasoning=str(data["reasoning"]),
            market_id=market.market_id,
        )
        return result
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse Claude response for %s: %s | raw: %r",
                     market.market_id, exc, text[:200])
        return None


class MarketAnalyst:
    """
    Stateful analyst that wraps the Claude API and respects config.

    Usage::

        analyst = MarketAnalyst.from_config(cfg)
        result = analyst.analyse(market)
        if result and result.is_actionable():
            ...
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-6",
        max_tokens: int = 1024,
        min_edge: float = 0.08,
        min_confidence: float = 0.65,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._min_edge = min_edge
        self._min_confidence = min_confidence

    @classmethod
    def from_config(cls, cfg: "Config") -> "MarketAnalyst":  # noqa: F821
        return cls(
            api_key=cfg.claude_analyst.api_key,
            model=cfg.claude_analyst.model,
            max_tokens=cfg.claude_analyst.max_tokens,
            min_edge=cfg.claude_analyst.min_edge,
            min_confidence=cfg.claude_analyst.min_confidence,
        )

    def analyse(self, market: MarketSnapshot) -> Optional[AnalysisResult]:
        return analyse_market(
            market,
            api_key=self._api_key,
            model=self._model,
            max_tokens=self._max_tokens,
            min_edge=self._min_edge,
            min_confidence=self._min_confidence,
        )

    def analyse_batch(
        self, markets: list, max_calls: int = 8
    ) -> list:
        """Analyse up to max_calls markets; return actionable results only."""
        results = []
        for m in markets[:max_calls]:
            result = self.analyse(m)
            if result and result.is_actionable(self._min_edge, self._min_confidence):
                results.append(result)
        return results
