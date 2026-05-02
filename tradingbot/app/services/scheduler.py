"""APScheduler-based scheduler service.

Manages the single recurring "daily analysis" job.
The trigger time is persisted in the DB so that WhatsApp ``schedule HH:MM``
commands survive restarts.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

JOB_ID = "daily_analysis"


# ---------------------------------------------------------------------------
# Daily analysis job
# ---------------------------------------------------------------------------


async def _daily_analysis_job() -> None:
    """Analyse every watchlist stock and push results to WhatsApp."""
    from datetime import date

    from app.db.session import get_db, get_watchlist, save_analysis
    from app.services.trading_agent import analyze_stock
    from app.services.discord_service import broadcast_discord_analysis_card, send_to_channel as discord_notify
    from app.services.whatsapp import broadcast, broadcast_analysis_card, format_daily_digest

    logger.info("Daily analysis job started")

    with get_db() as db:
        stocks = get_watchlist(db)

    tickers = [s.ticker for s in stocks]

    if not tickers:
        await broadcast("📭 Watchlist is empty – nothing to analyse.\nUse *add TICKER* to add stocks.")
        await discord_notify("📭 Watchlist is empty – nothing to analyse.")
        return

    start_msg = (
        f"🔍 Starting daily analysis for {len(tickers)} stock(s): "
        + ", ".join(f"*{t}*" for t in tickers)
        + " …"
    )
    await broadcast(start_msg)
    await discord_notify(start_msg)

    today = date.today().strftime("%Y-%m-%d")
    results: list[dict] = []

    for ticker in tickers:
        result = await analyze_stock(ticker, today)
        results.append(result)

        # Persist each result immediately
        with get_db() as db:
            save_analysis(
                db,
                ticker=result["ticker"],
                analysis_date=result["date"],
                decision=result["decision"],
                short_summary=result["short_summary"],
                full_report=result["full_report"],
                success=result["success"],
                error_message=result.get("error"),
            )

        # Push to WhatsApp and Discord simultaneously
        await broadcast_analysis_card(
            result["ticker"],
            result["date"],
            result["decision"],
            result["short_summary"],
            rich=result.get("rich"),
        )
        await broadcast_discord_analysis_card(
            result["ticker"],
            result["date"],
            result["decision"],
            result["short_summary"],
            rich=result.get("rich"),
        )

    # Final digest summary
    digest = format_daily_digest(results)
    await broadcast(digest)
    await discord_notify(digest)

    logger.info("Daily analysis job finished (%d stocks)", len(tickers))


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

    hour, minute = _parse_hhmm(analysis_time)

    _scheduler.add_job(
        _daily_analysis_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id=JOB_ID,
        name="Daily Stock Analysis",
        replace_existing=True,
        misfire_grace_time=3600,  # run even if missed by up to 1 hour
    )

    _scheduler.start()
    logger.info("Scheduler started – daily analysis at %s (%s)", analysis_time, timezone)


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def reschedule(time_str: str, timezone: str | None = None) -> None:
    """Update the daily analysis trigger and persist the new time."""
    from app.db.session import get_config, get_db, set_config

    hour, minute = _parse_hhmm(time_str)

    with get_db() as db:
        if timezone is None:
            timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)
        set_config(db, "analysis_time", time_str)

    trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
    _scheduler.reschedule_job(JOB_ID, trigger=trigger)
    logger.info("Daily analysis rescheduled to %s (%s)", time_str, timezone)


def next_run_info() -> str:
    """Human-readable next run time, or a descriptive fallback."""
    job = _scheduler.get_job(JOB_ID)
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
