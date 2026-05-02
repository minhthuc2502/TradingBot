"""Async wrapper around the TradingAgentsGraph.

TradingAgents is synchronous (LangGraph + blocking LLM calls), so every
``propagate()`` call is dispatched to a ``ThreadPoolExecutor`` to avoid
blocking the FastAPI event loop.

A semaphore caps the number of concurrent analyses to avoid exhausting
your LLM API quota.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Thread pool shared across all analyses (workers == max concurrent)
_executor = ThreadPoolExecutor(
    max_workers=settings.max_concurrent_analyses,
    thread_name_prefix="trading-agent",
)

# Async semaphore as an extra guard (matches executor workers)
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)
    return _semaphore


# ---------------------------------------------------------------------------
# Synchronous core (runs in thread pool)
# ---------------------------------------------------------------------------


def _build_ta_config(model: str | None = None) -> dict[str, Any]:
    """Build TradingAgents config dict. If model is a Gemini model name, override provider."""
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = settings.max_debate_rounds
    config["online_tools"] = settings.online_tools

    if model and "gemini" in model.lower():
        config["llm_provider"] = "google"
        config["deep_think_llm"] = model
        config["quick_think_llm"] = model
        config["backend_url"] = None
    else:
        config["llm_provider"] = settings.llm_provider
        config["deep_think_llm"] = settings.deep_think_llm
        config["quick_think_llm"] = settings.quick_think_llm
        if settings.llm_provider.lower() != "openai":
            config["backend_url"] = None

    return config


def _inject_api_keys() -> None:
    """Push API keys from settings into os.environ so LangChain clients find them.

    pydantic-settings loads .env into Python attributes but does NOT export them
    to the process environment. Libraries like langchain_google_genai read
    os.environ directly, so we must set the variables ourselves.
    """
    import os

    key_map = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "GOOGLE_API_KEY": settings.google_api_key,
        "GEMINI_API_KEY": settings.google_api_key,  # some langchain versions use this
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "XAI_API_KEY": settings.xai_api_key,
        "ALPHA_VANTAGE_API_KEY": settings.alpha_vantage_api_key,
    }
    for env_var, value in key_map.items():
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


def _run_analysis_sync(ticker: str, analysis_date: str, model: str | None = None) -> dict:
    """
    Execute TradingAgents propagate() synchronously.

    Returns a dict with all report sections extracted from final_state.
    """
    from tradingagents.graph.trading_graph import TradingAgentsGraph  # lazy import

    _inject_api_keys()
    config = _build_ta_config(model)
    ta = TradingAgentsGraph(debug=False, config=config)
    final_state, decision = ta.propagate(ticker, analysis_date)

    decision_str = str(decision)
    decision_label = _extract_decision_label(decision_str)

    return {
        "decision_label": decision_label,
        "final_trade_decision": final_state.get("final_trade_decision", decision_str),
        "market_report": final_state.get("market_report", ""),
        "sentiment_report": final_state.get("sentiment_report", ""),
        "news_report": final_state.get("news_report", ""),
        "fundamentals_report": final_state.get("fundamentals_report", ""),
        "trader_investment_plan": final_state.get("trader_investment_plan", ""),
        "investment_plan": final_state.get("investment_plan", ""),
        "risk_judge_decision": (
            final_state.get("risk_debate_state", {}).get("judge_decision", "")
        ),
        "invest_judge_decision": (
            final_state.get("investment_debate_state", {}).get("judge_decision", "")
        ),
    }


def _extract_decision_label(text: str) -> str:
    """Pull the primary BUY / SELL / HOLD label from the agent output."""
    upper = text.upper()

    # Prioritise multi-word labels
    for label in ("STRONG BUY", "STRONG SELL", "STRONG_BUY", "STRONG_SELL"):
        if label in upper:
            return label.replace("_", " ")

    # Regex patterns to locate explicit decision declarations
    patterns = [
        r"\bFINAL\s+DECISION\s*[:\-]\s*([A-Z ]+)",
        r"\bDECISION\s*[:\-]\s*([A-Z ]+)",
        r"\bRECOMMENDATION\s*[:\-]\s*([A-Z ]+)",
        r"\bACTION\s*[:\-]\s*([A-Z ]+)",
        r"\b(BUY|SELL|HOLD)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            fragment = match.group(1).strip()
            for label in ("STRONG BUY", "STRONG SELL", "BUY", "SELL", "HOLD"):
                if label in fragment:
                    return label

    return "UNKNOWN"


def _extract_short_summary(text: str) -> str:
    """Return the first 2-3 meaningful sentences as a short summary."""
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40]
    excerpt = " ".join(lines[:3])
    return excerpt[:400] if len(excerpt) > 400 else excerpt


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def analyze_stock(ticker: str, analysis_date: str | None = None, model: str | None = None) -> dict:
    """
    Run a full TradingAgents analysis for *ticker* on *analysis_date*.

    Returns a dict with keys:
      ticker, date, decision, short_summary, full_report, success, error
    """
    if analysis_date is None:
        analysis_date = date.today().strftime("%Y-%m-%d")

    loop = asyncio.get_event_loop()
    async with _get_semaphore():
        try:
            logger.info("Analysis started: %s @ %s", ticker, analysis_date)
            rich = await loop.run_in_executor(
                _executor,
                functools.partial(_run_analysis_sync, ticker, analysis_date, model),
            )
            decision_label = rich["decision_label"]
            logger.info("Analysis complete: %s → %s", ticker, decision_label)
            return {
                "ticker": ticker,
                "date": analysis_date,
                "decision": decision_label,
                # short_summary kept for DB / digest (first 400 chars of final decision)
                "short_summary": _extract_short_summary(rich["final_trade_decision"]),
                "full_report": rich["final_trade_decision"],
                # rich sections for the detailed WhatsApp card
                "rich": rich,
                "success": True,
                "error": None,
            }
        except Exception as exc:
            logger.exception("Analysis failed for %s: %s", ticker, exc)
            return {
                "ticker": ticker,
                "date": analysis_date,
                "decision": "ERROR",
                "short_summary": f"Analysis failed: {exc}",
                "full_report": str(exc),
                "rich": {},
                "success": False,
                "error": str(exc),
            }
