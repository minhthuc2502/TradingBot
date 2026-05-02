from __future__ import annotations

import json
import logging
import re

from app.agents.discovery.schemas import DiscoveryState
from app.agents.discovery.tools import (
    detect_breakout,
    get_news_active_tickers,
    screen_volume_anomalies,
)
from app.config import settings

logger = logging.getLogger(__name__)


def _get_discovery_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=settings.analysis_model,
        google_api_key=settings.google_api_key,
        temperature=0.1,
    )


def _parse_candidates(content: str) -> list[dict]:
    """Extract JSON array of candidate dicts from LLM response."""
    try:
        text = re.sub(r"```(?:json)?\n?", "", content).strip().rstrip("`")
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as exc:
        logger.warning("_parse_candidates failed: %s | content: %.200s", exc, content)
    return []


def volume_analyst_node(state: DiscoveryState) -> dict:
    """Screen universe for volume anomalies; return top candidates."""
    raw = screen_volume_anomalies(state["universe"], date=state["discovery_date"])
    if not raw:
        logger.info("Volume analyst: no anomalies found")
        return {"volume_candidates": []}

    top = sorted(raw, key=lambda x: x["volume_ratio"], reverse=True)[:25]
    context = "\n".join(
        f"- {c['ticker']}: {c['volume_ratio']:.1f}x average volume" for c in top
    )

    llm = _get_discovery_llm()
    prompt = (
        f"You are a Volume Analyst. Today ({state['discovery_date']}) these stocks show unusual volume:\n"
        f"{context}\n\n"
        "Select the 5-8 most significant stocks for further analysis. "
        "Focus on those with the highest volume that suggest institutional activity or a major catalyst. "
        "Return ONLY a JSON array (no markdown) with objects: "
        '{"ticker": "X", "confluence_score": 1.0, "signals": ["volume_spike"], "priority": "HIGH|MEDIUM|LOW"}'
    )

    try:
        response = llm.invoke(prompt)
        candidates = _parse_candidates(response.content)
    except Exception as exc:
        logger.warning("Volume analyst LLM call failed: %s — using rule-based fallback", exc)
        candidates = [
            {"ticker": c["ticker"], "confluence_score": 1.0, "signals": ["volume_spike"], "priority": "HIGH"}
            for c in top[:8]
        ]

    logger.info("Volume analyst selected %d candidates", len(candidates))
    return {"volume_candidates": candidates}


def news_scanner_node(state: DiscoveryState) -> dict:
    """Find tickers with active news coverage; return candidates."""
    raw = get_news_active_tickers(state["universe"])
    if not raw:
        logger.info("News scanner: no active news tickers found")
        return {"news_candidates": []}

    context = "\n".join(
        f"- {c['ticker']}: {c['news_count']} recent articles" for c in raw[:20]
    )

    llm = _get_discovery_llm()
    prompt = (
        f"You are a News Analyst. Today ({state['discovery_date']}) these stocks have active news coverage:\n"
        f"{context}\n\n"
        "Select the 5-8 stocks where news activity suggests a material development "
        "(earnings, M&A, product launch, regulatory action). "
        "Return ONLY a JSON array (no markdown): "
        '{"ticker": "X", "confluence_score": 1.0, "signals": ["news_active"], "priority": "HIGH|MEDIUM|LOW"}'
    )

    try:
        response = llm.invoke(prompt)
        candidates = _parse_candidates(response.content)
    except Exception as exc:
        logger.warning("News scanner LLM call failed: %s — using rule-based fallback", exc)
        candidates = [
            {"ticker": c["ticker"], "confluence_score": 1.0, "signals": ["news_active"], "priority": "MEDIUM"}
            for c in raw[:8]
        ]

    logger.info("News scanner selected %d candidates", len(candidates))
    return {"news_candidates": candidates}


def technical_screener_node(state: DiscoveryState) -> dict:
    """Check technical setups; prioritise tickers already found by other screeners."""
    existing_tickers = {
        c["ticker"]
        for c in state.get("volume_candidates", []) + state.get("news_candidates", [])
    }
    sample = [t for t in state["universe"][:50] if t not in existing_tickers][:20]
    to_check = list(existing_tickers) + sample

    technical_candidates = []
    for ticker in to_check:
        result = detect_breakout(ticker, date=state["discovery_date"])
        if result:
            priority = "HIGH" if ticker in existing_tickers else "MEDIUM"
            technical_candidates.append({
                "ticker": ticker,
                "confluence_score": 1.0,
                "signals": result.get("signals", ["technical_setup"]),
                "priority": priority,
            })

    logger.info("Technical screener found %d candidates", len(technical_candidates))
    return {"technical_candidates": technical_candidates}
