"""APScheduler-based scheduler service.

Phase 1 (discovery): runs at DISCOVERY_TIME (default 23:00 UTC)
  → DiscoveryGraph screens universe for candidates
  → Merges with manual watchlist → stored in _discovery_signal_map

Phase 2 (analysis): runs at ANALYSIS_TIME (default 00:00 UTC)
  → EnsembleService analyzes each ticker (pro + flash Gemini in parallel)
  → Sends Discord embed card per ticker as results arrive
  → Sends session summary at end
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

ANALYSIS_JOB_ID = "daily_analysis"
DISCOVERY_JOB_ID = "daily_discovery"

# Discovery results: ticker → list of signals (populated by discovery job)
_discovery_signal_map: Dict[str, List[str]] = {}


# ---------------------------------------------------------------------------
# Phase 1: Discovery job
# ---------------------------------------------------------------------------


async def _daily_discovery_job() -> List[str]:
    """Run DiscoveryGraph and store results for the analysis job."""
    if not settings.discovery_enabled:
        logger.info("Discovery disabled by config")
        return []

    from app.agents.discovery.graph import run_discovery
    from app.services.discord_service import send_to_channel

    today = date.today().strftime("%Y-%m-%d")
    logger.info("Discovery job started for %s", today)

    try:
        selected = await run_discovery(date=today)
        global _discovery_signal_map
        _discovery_signal_map = {ticker: ["auto_discovered"] for ticker in selected}
        logger.info("Discovery complete: %d candidates → %s", len(selected), selected)

        if selected:
            await send_to_channel(
                f"🔭 Discovery complete: found {len(selected)} candidates — "
                + ", ".join(f"**{t}**" for t in selected)
            )
        return selected
    except Exception as exc:
        logger.exception("Discovery job failed: %s", exc)
        await send_to_channel(f"⚠️ Discovery job failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Phase 2: Analysis job
# ---------------------------------------------------------------------------


async def _daily_analysis_job() -> None:
    """Analyse every ticker (watchlist + discovered) and push Discord embeds."""
    from app.agents.ensemble.schemas import ConsensusPlan
    from app.agents.ensemble.service import run_ensemble
    from app.db.session import get_db, get_watchlist, save_analysis
    from app.services.discord_service import (
        send_analysis_embed,
        send_session_summary,
        send_to_channel,
    )
    from app.services.whatsapp import broadcast

    logger.info("Daily analysis job started")

    with get_db() as db:
        stocks = get_watchlist(db)

    watchlist_tickers = [s.ticker for s in stocks]
    discovered = list(_discovery_signal_map.keys())
    all_tickers = list(dict.fromkeys(watchlist_tickers + discovered))

    if not all_tickers:
        msg = "📭 Watchlist is empty and no stocks discovered — nothing to analyse."
        await broadcast(msg)
        await send_to_channel(msg)
        return

    today = date.today().strftime("%Y-%m-%d")
    start_msg = (
        f"🔍 Starting ensemble analysis for {len(all_tickers)} stock(s): "
        + ", ".join(f"**{t}**" for t in all_tickers)
    )
    await send_to_channel(start_msg)
    await broadcast(start_msg.replace("**", "*"))

    all_plans: List[ConsensusPlan] = []

    for ticker in all_tickers:
        signals = _discovery_signal_map.get(ticker, [])
        try:
            plan = await run_ensemble(ticker, today, discovery_signals=signals)
            all_plans.append(plan)

            with get_db() as db:
                save_analysis(
                    db,
                    ticker=plan.ticker,
                    analysis_date=plan.trade_date,
                    decision=plan.final_rating,
                    short_summary=plan.executive_summary,
                    full_report=plan.executive_summary,
                    success=True,
                    error_message=None,
                    confidence_score=plan.confidence_score,
                    model_agreement=plan.model_agreement,
                )

            await send_analysis_embed(plan)
            await broadcast(
                f"*{plan.ticker}* → {plan.final_rating} "
                f"({int(plan.confidence_score * 100)}% confidence)\n"
                f"{plan.executive_summary}"
            )

        except RuntimeError as exc:
            logger.error("Both models failed for %s: %s", ticker, exc)
            await send_to_channel(f"❌ Analysis failed for **{ticker}**: {exc}")
            with get_db() as db:
                save_analysis(
                    db,
                    ticker=ticker,
                    analysis_date=today,
                    decision="ERROR",
                    short_summary=str(exc),
                    full_report=str(exc),
                    success=False,
                    error_message=str(exc),
                )

        except Exception as exc:
            logger.exception("Unexpected error analysing %s: %s", ticker, exc)
            await send_to_channel(f"❌ Unexpected error for **{ticker}**: {exc}")

    if all_plans:
        await send_session_summary(all_plans, today)

    logger.info("Daily analysis job finished (%d stocks)", len(all_tickers))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def start_scheduler() -> None:
    """Load persisted config, register both jobs, and start the scheduler."""
    from app.db.session import get_config, get_db

    with get_db() as db:
        analysis_time = get_config(db, "analysis_time", settings.analysis_time)
        timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)

    a_hour, a_minute = _parse_hhmm(analysis_time)
    d_hour, d_minute = _parse_hhmm(settings.discovery_time)

    _scheduler.add_job(
        _daily_analysis_job,
        trigger=CronTrigger(hour=a_hour, minute=a_minute, timezone=timezone),
        id=ANALYSIS_JOB_ID,
        name="Daily Ensemble Analysis",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    if settings.discovery_enabled:
        _scheduler.add_job(
            _daily_discovery_job,
            trigger=CronTrigger(hour=d_hour, minute=d_minute, timezone=timezone),
            id=DISCOVERY_JOB_ID,
            name="Daily Stock Discovery",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    _scheduler.start()
    logger.info(
        "Scheduler started — discovery at %s, analysis at %s (%s)",
        settings.discovery_time,
        analysis_time,
        timezone,
    )


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def reschedule(time_str: str, timezone: str | None = None) -> None:
    """Update the analysis trigger and persist the new time."""
    from app.db.session import get_config, get_db, set_config

    hour, minute = _parse_hhmm(time_str)

    with get_db() as db:
        if timezone is None:
            timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)
        set_config(db, "analysis_time", time_str)

    trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
    _scheduler.reschedule_job(ANALYSIS_JOB_ID, trigger=trigger)
    logger.info("Analysis rescheduled to %s (%s)", time_str, timezone)


def next_run_info() -> str:
    job = _scheduler.get_job(ANALYSIS_JOB_ID)
    if not job or not job.next_run_time:
        return "not scheduled"
    return job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format '{time_str}' – expected HH:MM")
    return int(parts[0]), int(parts[1])
