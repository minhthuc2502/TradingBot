"""WhatsApp messaging layer backed by Twilio.

All outbound sends are wrapped in an async helper so they can be called
from async route handlers without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Sequence

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from app.config import settings

logger = logging.getLogger(__name__)

# Decision → emoji mapping (WhatsApp supports Unicode)
_DECISION_EMOJI: dict[str, str] = {
    "STRONG BUY": "🟢",
    "BUY": "🟩",
    "HOLD": "🟡",
    "SELL": "🟥",
    "STRONG SELL": "🔴",
    "ERROR": "❌",
    "UNKNOWN": "⚪",
}


@lru_cache(maxsize=1)
def _get_client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _normalise_number(number: str) -> str:
    """Ensure number has the ``whatsapp:`` prefix."""
    number = number.strip()
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


# ---------------------------------------------------------------------------
# Low-level send (synchronous – use async_send_message from async code)
# ---------------------------------------------------------------------------


def send_message(to: str, body: str) -> bool:
    """Send a WhatsApp message. Returns True on success."""
    try:
        _get_client().messages.create(
            from_=settings.twilio_whatsapp_from,
            to=_normalise_number(to),
            body=body,
        )
        logger.debug("Sent WhatsApp to %s", to)
        return True
    except TwilioRestException as exc:
        logger.error("Twilio error sending to %s: %s", to, exc)
        return False


async def async_send_message(to: str, body: str) -> bool:
    """Non-blocking wrapper around ``send_message``."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_message, to, body)


async def broadcast(body: str) -> None:
    """Send *body* to every authorised number concurrently."""
    numbers = settings.authorized_number_list
    if not numbers:
        logger.warning("broadcast() called but AUTHORIZED_NUMBERS is empty")
        return
    await asyncio.gather(*(async_send_message(n, body) for n in numbers))


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------


_MAX_MSG = 1500  # safe margin below Twilio's 1600-char hard limit


def _split_into_chunks(text: str, max_len: int = _MAX_MSG) -> list[str]:
    """
    Split *text* into chunks that each fit within *max_len* characters.

    Splits at paragraph boundaries (double newline) first, then at single
    newlines, and finally by character if a single line is still too long.
    No content is ever trimmed or lost.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""

    # Walk paragraph by paragraph
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).lstrip("\n") if current else para
        if len(candidate) <= max_len:
            current = candidate
        else:
            # Current paragraph doesn't fit — flush what we have
            if current:
                chunks.append(current.strip())
                current = ""
            # Try line-by-line within this paragraph
            for line in para.split("\n"):
                candidate = (current + "\n" + line).lstrip("\n") if current else line
                if len(candidate) <= max_len:
                    current = candidate
                else:
                    if current:
                        chunks.append(current.strip())
                        current = ""
                    # Line itself too long — hard-split by character
                    while len(line) > max_len:
                        chunks.append(line[:max_len])
                        line = line[max_len:]
                    current = line

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c]


async def _summarize_all_sections(combined: str) -> str:
    """
    Use the quick LLM to produce one concise analyst summary from all sections.
    Returns a bullet-point digest keeping only the key signals and conclusions.
    Falls back to the raw combined text if the call fails.
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # lazy import
        from langchain_core.messages import HumanMessage

        llm = ChatGoogleGenerativeAI(model=settings.quick_think_llm)
        prompt = (
            "You are a concise financial analyst assistant.\n"
            "Below are multiple analyst sections from a stock trading analysis report "
            "(market/technical, news, sentiment, fundamentals, debate, trader plan, risk).\n"
            "Combine them into ONE short analyst digest. Rules:\n"
            "- Keep only the most important signals, key numbers, and final conclusions.\n"
            "- Use short bullet points grouped by topic.\n"
            "- Maximum 1 400 characters total.\n"
            "- Do NOT repeat the trade decision — that is already sent separately.\n\n"
            f"{combined}"
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            # Gemini may return a list of content parts — join text parts
            content = " ".join(
                part if isinstance(part, str) else (part.get("text", "") if isinstance(part, dict) else str(part))
                for part in content
            )
        return (content or "").strip()
    except Exception as exc:
        logger.warning("LangChain combined summarisation failed: %s", exc)
        return combined  # fallback — caller will split by paragraph


async def format_analysis_messages(
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str,
    rich: dict | None = None,
) -> list[str]:
    """
    Return WhatsApp messages for a full analysis — two logical parts:

    1. Decision + quick reason  (from final_trade_decision, LLM-summarised if long)
    2. Analyst digest           (all sections combined → one LLM summary → split if needed)
    """
    emoji = _DECISION_EMOJI.get(decision, "⚪")
    messages: list[str] = []
    prefix = f"📊 *{ticker}  —  {analysis_date}*\n"

    # ── Part 1: decision + reason ────────────────────────────────────────────
    final = (rich or {}).get("final_trade_decision", "") or short_summary or ""
    # Summarise the decision reasoning if it is too long
    if len(final) > _MAX_MSG:
        final = await _summarize_all_sections(
            f"Final trade decision:\n{final}\n\nSummarise the key reasoning in under 1 000 characters."
        )
    decision_block = (
        f"{prefix}{emoji} *DECISION: {decision}*\n\n"
        f"✅ *Reasoning*\n{final.strip()}"
    )
    for chunk in _split_into_chunks(decision_block):
        messages.append(chunk)

    if not rich:
        return messages

    # ── Part 2: all analyst sections → one combined LLM digest ───────────────
    section_texts = []
    section_map = [
        ("Market / Technical",  rich.get("market_report")),
        ("News",                rich.get("news_report")),
        ("Sentiment",           rich.get("sentiment_report")),
        ("Fundamentals",        rich.get("fundamentals_report")),
        ("Investment Debate",   rich.get("invest_judge_decision")),
        ("Trader Plan",         rich.get("trader_investment_plan") or rich.get("investment_plan")),
        ("Risk Assessment",     rich.get("risk_judge_decision")),
    ]
    for label, content in section_map:
        if content and content.strip():
            section_texts.append(f"### {label}\n{content.strip()}")

    if section_texts:
        combined_raw = "\n\n".join(section_texts)
        digest = await _summarize_all_sections(combined_raw)
        digest_block = f"{prefix}🔍 *Analyst Digest*\n\n{digest}"
        for chunk in _split_into_chunks(digest_block):
            messages.append(chunk)

    return messages



async def send_analysis_card(
    to: str,
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str,
    rich: dict | None = None,
) -> None:
    """Send all analysis messages for one stock sequentially to *to*."""
    for msg in await format_analysis_messages(ticker, analysis_date, decision, short_summary, rich):
        await async_send_message(to, msg)


async def broadcast_analysis_card(
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str,
    rich: dict | None = None,
) -> None:
    """Broadcast a full analysis to every authorised number."""
    for msg in await format_analysis_messages(ticker, analysis_date, decision, short_summary, rich):
        await broadcast(msg)


def format_analysis_card(
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str,
    rich: dict | None = None,  # noqa: ARG001
) -> str:
    """Compact single-message card used by digest/report (no section split)."""
    emoji = _DECISION_EMOJI.get(decision, "⚪")
    return (
        f"📊 *{ticker}  —  {analysis_date}*\n"
        f"{emoji} *DECISION: {decision}*\n\n"
        f"{(short_summary or 'No summary available.')}"
    )


def format_daily_digest(analyses: Sequence[dict]) -> str:
    """One-line summary per stock for the daily push notification."""
    if not analyses:
        return "📭 No analysis results to report."

    lines = ["📅 *Daily Analysis Digest*\n"]
    for a in analyses:
        emoji = _DECISION_EMOJI.get(a.get("decision", ""), "⚪")
        lines.append(f"{emoji} *{a['ticker']}*  —  {a.get('decision', '?')}")

    lines.append("\nReply *report* to see the full details.")
    return "\n".join(lines)


def format_watchlist(tickers: list[str]) -> str:
    if not tickers:
        return "📭 Your watchlist is empty.\nUse *add TICKER* to add stocks."
    items = "\n".join(f"  • {t}" for t in tickers)
    return f"📋 *Watchlist  ({len(tickers)} stocks)*\n\n{items}"
