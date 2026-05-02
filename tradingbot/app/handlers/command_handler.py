"""WhatsApp command router.

Parses raw message text sent by a user and dispatches to the appropriate
handler. All slow operations (stock analysis) are run as fire-and-forget
async tasks so the command handler itself responds immediately.

Supported commands
------------------
  help                         – Show available commands
  list                         – Show watchlist
  add TICKER                   – Add ticker to watchlist
  remove TICKER                – Remove ticker from watchlist
  analyze TICKER [YYYY-MM-DD]  – Run on-demand analysis
  report                       – Show latest cached analysis for watchlist
  schedule HH:MM               – Reschedule daily analysis
  next                         – Show next scheduled run
  status                       – Show bot health summary
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from app.config import settings
from app.db.session import (
    add_stock,
    get_config,
    get_db,
    get_latest_analyses,
    get_watchlist,
    remove_stock,
    stock_exists,
)
from app.services.scheduler import next_run_info, reschedule
from app.services.whatsapp import (
    async_send_message,
    format_analysis_card,
    format_watchlist,
    send_analysis_card,
)

logger = logging.getLogger(__name__)

# Valid ticker pattern: 1-20 characters, letters/digits/dot/colon/dash
_TICKER_RE = re.compile(r"^[A-Z0-9.:\-]{1,20}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

HELP_TEXT = (
    "🤖 *TradingBot Commands*\n\n"
    "📋 *Watchlist*\n"
    "  `list`  —  Show your watchlist\n"
    "  `add TICKER`  —  Add a stock\n"
    "  `remove TICKER`  —  Remove a stock\n\n"
    "📊 *Analysis*\n"
    "  `analyze TICKER`  —  Analyse a stock right now\n"
    "  `analyze TICKER YYYY-MM-DD`  —  Analyse on a specific date\n"
    "  `report`  —  Latest results for all watchlist stocks\n\n"
    "⚙️ *Settings*\n"
    "  `schedule HH:MM`  —  Change daily analysis time (UTC)\n"
    "  `next`  —  When is the next scheduled run?\n"
    "  `status`  —  Bot health summary\n\n"
    "Type *help* to see this message again."
)


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


def is_authorised(from_number: str) -> bool:
    """Return True if the sender may use the bot."""
    allowed = settings.authorized_number_list
    if not allowed:
        return True  # open access when AUTHORIZED_NUMBERS is not configured
    clean = from_number.replace("whatsapp:", "").strip()
    return clean in allowed or from_number in allowed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def handle_message(from_number: str, raw_body: str, *, skip_auth: bool = False) -> str:
    """
    Parse *raw_body* and return an immediate response string.

    Long-running operations (analysis) are dispatched as background tasks
    and will push their results directly to the user via WhatsApp.

    Pass ``skip_auth=True`` when the caller has already validated the sender
    (e.g. the Discord bot performs its own authorisation check).
    """
    if not skip_auth and not is_authorised(from_number):
        logger.warning("Unauthorised access attempt from %s", from_number)
        return "🚫 You are not authorised to use this bot."

    text = raw_body.strip()
    lower = text.lower()

    if lower == "help":
        return HELP_TEXT

    if lower == "list":
        return _cmd_list()

    if lower == "report":
        return _cmd_report()

    if lower == "next":
        return f"⏰ Next daily analysis: *{next_run_info()}*"

    if lower == "status":
        return _cmd_status()

    # add TICKER
    m = re.match(r"^add\s+(\S+)$", text, re.IGNORECASE)
    if m:
        return _cmd_add(m.group(1).upper(), from_number)

    # remove TICKER
    m = re.match(r"^remove\s+(\S+)$", text, re.IGNORECASE)
    if m:
        return _cmd_remove(m.group(1).upper())

    # analyze TICKER [YYYY-MM-DD]
    m = re.match(r"^analyze\s+(\S+)(?:\s+(\d{4}-\d{2}-\d{2}))?$", text, re.IGNORECASE)
    if m:
        ticker = m.group(1).upper()
        analysis_date = m.group(2) or date.today().strftime("%Y-%m-%d")
        if not _TICKER_RE.match(ticker):
            return f"❌ Invalid ticker format: *{ticker}*"
        if m.group(2) and not _DATE_RE.match(m.group(2)):
            return "❌ Invalid date format – use YYYY-MM-DD."

        # Fire-and-forget: result sent via WhatsApp when ready
        asyncio.create_task(_bg_analyze_and_reply(from_number, ticker, analysis_date))
        return (
            f"🔍 Analysing *{ticker}* for {analysis_date}…\n"
            "I'll send you the results in a few minutes."
        )

    # schedule HH:MM
    m = re.match(r"^schedule\s+(\d{1,2}:\d{2})$", text, re.IGNORECASE)
    if m:
        return _cmd_schedule(m.group(1))

    return f"❓ Unknown command: `{text}`\nType *help* to see available commands."


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _cmd_list() -> str:
    with get_db() as db:
        stocks = get_watchlist(db)
    return format_watchlist([s.ticker for s in stocks])


def _cmd_add(ticker: str, from_number: str) -> str:
    if not _TICKER_RE.match(ticker):
        return f"❌ Invalid ticker format: *{ticker}*"
    with get_db() as db:
        if stock_exists(db, ticker):
            return f"ℹ️ *{ticker}* is already in your watchlist."
        add_stock(db, ticker, added_by=from_number)
    return f"✅ *{ticker}* added to watchlist."


def _cmd_remove(ticker: str) -> str:
    with get_db() as db:
        removed = remove_stock(db, ticker)
    return (
        f"✅ *{ticker}* removed from watchlist."
        if removed
        else f"ℹ️ *{ticker}* is not in your watchlist."
    )


def _cmd_report() -> str:
    with get_db() as db:
        stocks = get_watchlist(db)
        tickers = [s.ticker for s in stocks]
        if not tickers:
            return "📭 Your watchlist is empty.\nUse *add TICKER* to get started."
        analyses = get_latest_analyses(db, tickers)

    if not analyses:
        return (
            "📭 No analysis results yet.\n"
            "Use *analyze TICKER* or wait for the daily run."
        )

    lines = ["📊 *Latest Analysis Report*\n"]
    emoji_map = {
        "STRONG BUY": "🟢",
        "BUY": "🟩",
        "HOLD": "🟡",
        "SELL": "🟥",
        "STRONG SELL": "🔴",
    }
    for a in analyses:
        emoji = emoji_map.get(a.decision, "⚪")
        lines.append(f"{emoji} *{a.ticker}*  —  {a.decision}  ({a.analysis_date})")
        if a.short_summary:
            preview = (
                a.short_summary[:130] + "…"
                if len(a.short_summary) > 130
                else a.short_summary
            )
            lines.append(f"   _{preview}_")
        lines.append("")

    return "\n".join(lines).strip()


def _cmd_schedule(time_str: str) -> str:
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("out of range")
    except (ValueError, IndexError):
        return "❌ Invalid time. Use HH:MM  (e.g. *schedule 14:30*)"

    try:
        reschedule(time_str)
        return f"✅ Daily analysis rescheduled to *{time_str} UTC*."
    except Exception as exc:
        logger.exception("Reschedule failed: %s", exc)
        return f"❌ Could not reschedule: {exc}"


def _cmd_status() -> str:
    with get_db() as db:
        stock_count = len(get_watchlist(db))
        analysis_time = get_config(db, "analysis_time", settings.analysis_time)
        timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)

    return (
        f"🤖 *TradingBot Status*\n\n"
        f"📋 Watchlist:  {stock_count} stock(s)\n"
        f"⏰ Daily analysis:  {analysis_time} ({timezone})\n"
        f"🔜 Next run:  {next_run_info()}\n"
        f"✅ Bot is running"
    )


# ---------------------------------------------------------------------------
# Background analysis task
# ---------------------------------------------------------------------------


async def _bg_analyze_and_reply(from_number: str, ticker: str, analysis_date: str) -> None:
    """Run analysis in the background and push the result to the user."""
    from app.db.session import save_analysis
    from app.services.trading_agent import analyze_stock

    result = await analyze_stock(ticker, analysis_date)

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

    await send_analysis_card(
        from_number,
        result["ticker"],
        result["date"],
        result["decision"],
        result["short_summary"],
        rich=result.get("rich"),
    )
