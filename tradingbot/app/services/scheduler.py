"""APScheduler-based scheduler service.

Single daily job (ANALYSIS_TIME):
  1. If discovery is enabled, runs DiscoveryGraph first to find candidates.
  2. Merges discovered tickers with the manual watchlist.
  3. Analyses each ticker with a single model (settings.analysis_model).
  4. Sends Discord embed card per ticker + a session summary at the end.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db.session import get_db, get_watchlist, save_analysis
from app.schemas import AnalysisPlan
from app.services.discord_service import send_analysis_embed, send_session_summary, send_to_channel
from app.services.trading_agent import analyze_stock
from app.services.whatsapp import broadcast

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

ANALYSIS_JOB_ID = "daily_analysis"


# ---------------------------------------------------------------------------
# Combined daily job
# ---------------------------------------------------------------------------


async def _daily_job() -> None:
    """Run discovery (optional) then analyse all tickers and push Discord embeds."""

    today = date.today().strftime("%Y-%m-%d")
    logger.info("Daily job started for %s", today)

    # ---- Phase 1: optional discovery ----------------------------------------
    discovery_signal_map: dict[str, list[str]] = {}
    if settings.discovery_enabled:
        from app.agents.discovery.graph import run_discovery

        try:
            selected = await run_discovery(date=today)
            discovery_signal_map = {t: ["auto_discovered"] for t in selected}
            logger.info("Discovery found %d candidates: %s", len(selected), selected)
            if selected:
                await send_to_channel(
                    f"🔭 Discovery found {len(selected)} candidates — "
                    + ", ".join(f"**{t}**" for t in selected)
                )
        except Exception as exc:
            logger.exception("Discovery failed: %s", exc)
            await send_to_channel(f"⚠️ Discovery failed: {exc}")

    # ---- Phase 2: build ticker list -----------------------------------------
    with get_db() as db:
        stocks = get_watchlist(db)

    watchlist = [s.ticker for s in stocks]
    all_tickers = list(dict.fromkeys(watchlist + list(discovery_signal_map)))

    if not all_tickers:
        msg = "📭 Watchlist is empty and discovery found nothing — nothing to analyse."
        await broadcast(msg)
        await send_to_channel(msg)
        return

    start_msg = (
        f"🔍 Starting analysis for {len(all_tickers)} stock(s): "
        + ", ".join(f"**{t}**" for t in all_tickers)
    )
    await send_to_channel(start_msg)
    await broadcast(start_msg.replace("**", "*"))

    # ---- Phase 3: analyse each ticker ---------------------------------------
    all_plans: List[AnalysisPlan] = []

    for ticker in all_tickers:
        signals = discovery_signal_map.get(ticker, [])
        try:
            result = await analyze_stock(ticker, today, model=settings.analysis_model)

            plan = AnalysisPlan(
                ticker=ticker,
                trade_date=today,
                final_rating=result["decision"],
                executive_summary=result["short_summary"],
                model_agreement=settings.analysis_model,
                discovery_signals=signals,
            )
            all_plans.append(plan)

            with get_db() as db:
                save_analysis(
                    db,
                    ticker=ticker,
                    analysis_date=today,
                    decision=result["decision"],
                    short_summary=result["short_summary"],
                    full_report=result["full_report"],
                    success=result["success"],
                    error_message=result.get("error"),
                )

            await send_analysis_embed(plan)
            await broadcast(
                f"*{ticker}* → {result['decision']}\n{result['short_summary']}"
            )

        except Exception as exc:
            logger.exception("Analysis failed for %s: %s", ticker, exc)
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

    if all_plans:
        await send_session_summary(all_plans, today)

    logger.info("Daily job finished (%d stocks)", len(all_tickers))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def start_scheduler() -> None:
    """Load persisted config, register the daily job, and start the scheduler."""
    from app.db.session import get_config, get_db

    with get_db() as db:
        analysis_time = get_config(db, "analysis_time", settings.analysis_time)
        timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)

    a_hour, a_minute = _parse_hhmm(analysis_time)

    _scheduler.add_job(
        _daily_job,
        trigger=CronTrigger(hour=a_hour, minute=a_minute, timezone=timezone),
        id=ANALYSIS_JOB_ID,
        name="Daily Analysis",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    logger.info("Scheduler started — daily analysis at %s (%s)", analysis_time, timezone)


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
