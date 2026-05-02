from __future__ import annotations

import asyncio
import logging
from typing import List

from app.agents.ensemble.schemas import ConsensusPlan
from app.agents.ensemble.synthesizer import synthesize
from app.config import settings
from app.services.trading_agent import analyze_stock

logger = logging.getLogger(__name__)


async def run_ensemble(
    ticker: str,
    date: str,
    discovery_signals: List[str] | None = None,
) -> ConsensusPlan:
    """
    Run two TradingAgents instances in parallel (Pro + Flash) and synthesize.
    Falls back gracefully if one model fails.
    Raises RuntimeError if both models fail.
    """
    discovery_signals = discovery_signals or []

    pro_result, flash_result = await asyncio.gather(
        analyze_stock(ticker, date, model=settings.analysis_model),
        analyze_stock(ticker, date, model=settings.analysis_model),
    )

    pro_ok = pro_result.get("success", False)
    flash_ok = flash_result.get("success", False)

    if not pro_ok and not flash_ok:
        raise RuntimeError(
            f"Both models failed for {ticker}: "
            f"pro={pro_result.get('error')}, flash={flash_result.get('error')}"
        )

    if not pro_ok:
        logger.warning("Pro model failed for %s, using Flash only", ticker)
        return _single_model_plan(ticker, date, flash_result, "Flash", discovery_signals)

    if not flash_ok:
        logger.warning("Flash model failed for %s, using Pro only", ticker)
        return _single_model_plan(ticker, date, pro_result, "Pro", discovery_signals)

    return await synthesize(ticker, date, pro_result, flash_result, discovery_signals)


def _single_model_plan(
    ticker: str,
    date: str,
    result: dict,
    model_name: str,
    discovery_signals: List[str],
) -> ConsensusPlan:
    return ConsensusPlan(
        ticker=ticker,
        trade_date=date,
        final_rating=result.get("decision", "HOLD"),
        confidence_score=0.5,
        model_agreement=f"Single model ({model_name} fallback)",
        time_horizon="2-4 weeks",
        executive_summary=result.get("short_summary", ""),
        discovery_signals=discovery_signals,
    )
