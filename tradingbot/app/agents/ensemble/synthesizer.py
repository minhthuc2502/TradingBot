from __future__ import annotations

import json
import logging
import re
from typing import List

from app.agents.ensemble.schemas import ConsensusPlan
from app.config import settings

logger = logging.getLogger(__name__)

_RATING_ORDER = ["SELL", "UNDERWEIGHT", "HOLD", "OVERWEIGHT", "BUY"]

_SYNTHESIS_PROMPT = """You are a senior portfolio manager synthesizing two independent AI analyses of {ticker} for {trade_date}.

**Model A (Pro) Analysis — Rating: {pro_rating}**
{pro_report}

**Model B (Flash) Analysis — Rating: {flash_rating}**
{flash_report}

**Pre-computed confidence score:** {confidence:.0%} (based on rating agreement distance)

Synthesize into ONE consistent recommendation. If ratings differ, identify the stronger thesis.

Return ONLY a JSON object (no markdown fences):
{{
  "final_rating": "BUY|OVERWEIGHT|HOLD|UNDERWEIGHT|SELL",
  "entry_price": <float or null>,
  "stop_loss": <float or null>,
  "price_target": <float or null>,
  "time_horizon": "<string>",
  "executive_summary": "<2-3 sentences>",
  "key_catalysts": ["<catalyst 1>", "<catalyst 2>"],
  "key_risks": ["<risk 1>", "<risk 2>"]
}}"""


def calculate_confidence(rating_a: str, rating_b: str) -> float:
    """Rule-based confidence score from rating distance on a 5-point scale."""
    try:
        idx_a = _RATING_ORDER.index(rating_a.upper())
        idx_b = _RATING_ORDER.index(rating_b.upper())
        diff = abs(idx_a - idx_b)
        return {0: 1.0, 1: 0.75, 2: 0.50, 3: 0.25, 4: 0.0}.get(diff, 0.25)
    except ValueError:
        return 0.5


def build_model_agreement_str(pro_rating: str, flash_rating: str, final_rating: str) -> str:
    if pro_rating.upper() == flash_rating.upper():
        return f"Both: {final_rating}"
    return f"Pro={pro_rating} · Flash={flash_rating} — leaning {final_rating}"


async def synthesize(
    ticker: str,
    trade_date: str,
    pro_result: dict,
    flash_result: dict,
    discovery_signals: List[str],
) -> ConsensusPlan:
    """Call Gemini Pro to synthesize two model analyses into one ConsensusPlan."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    pro_rating = pro_result.get("decision", "HOLD")
    flash_rating = flash_result.get("decision", "HOLD")
    confidence = calculate_confidence(pro_rating, flash_rating)

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_pro_model,
        google_api_key=settings.google_api_key,
        temperature=0.1,
    )

    prompt = _SYNTHESIS_PROMPT.format(
        ticker=ticker,
        trade_date=trade_date,
        pro_rating=pro_rating,
        pro_report=pro_result.get("full_report", "")[:3000],
        flash_rating=flash_rating,
        flash_report=flash_result.get("full_report", "")[:3000],
        confidence=confidence,
    )

    try:
        response = await llm.ainvoke(prompt)
        text = response.content.strip()
        text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`")
        data = json.loads(text)
    except Exception as exc:
        logger.warning("ConsensusSynthesizer LLM call failed: %s — using fallback", exc)
        data = {
            "final_rating": pro_rating if pro_result.get("success") else flash_rating,
            "entry_price": None,
            "stop_loss": None,
            "price_target": None,
            "time_horizon": "2-4 weeks",
            "executive_summary": pro_result.get("short_summary") or flash_result.get("short_summary") or "",
            "key_catalysts": [],
            "key_risks": [],
        }

    final_rating = data.get("final_rating", "HOLD")

    return ConsensusPlan(
        ticker=ticker,
        trade_date=trade_date,
        final_rating=final_rating,
        confidence_score=confidence,
        model_agreement=build_model_agreement_str(pro_rating, flash_rating, final_rating),
        entry_price=data.get("entry_price"),
        stop_loss=data.get("stop_loss"),
        price_target=data.get("price_target"),
        time_horizon=data.get("time_horizon", "2-4 weeks"),
        executive_summary=data.get("executive_summary", ""),
        key_catalysts=data.get("key_catalysts", []),
        key_risks=data.get("key_risks", []),
        discovery_signals=discovery_signals,
    )
