"""Discord bot service.

Runs a discord.py bot inside the same asyncio event loop as FastAPI.
The bot listens for commands in any channel it can read and broadcasts
daily analysis results to a configured notification channel.

Setup (in the Discord Developer Portal)
----------------------------------------
1. Create an application + bot.
2. Under "Bot → Privileged Gateway Intents", enable *Message Content Intent*.
3. Invite the bot with scopes ``bot`` + permissions ``Send Messages``,
   ``Read Message History``, ``View Channels``.
4. Copy the bot token into ``DISCORD_BOT_TOKEN`` in your ``.env``.
5. Copy the notification channel ID into ``DISCORD_CHANNEL_ID``.

Supported commands (prefix-free, same as WhatsApp)
---------------------------------------------------
  help | list | add TICKER | remove TICKER
  analyze TICKER [YYYY-MM-DD] | report | schedule HH:MM | next | status
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

import discord

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Markdown conversion  (WhatsApp *bold* / _italic_ → Discord **bold** / *italic*)
# ---------------------------------------------------------------------------

_WA_BOLD_RE = re.compile(r"\*([^*\n]+)\*")
_WA_ITALIC_RE = re.compile(r"_([^_\n]+)_")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _fmt(text: str) -> str:
    """Convert WhatsApp markdown to Discord markdown."""
    text = _WA_BOLD_RE.sub(r"**\1**", text)
    text = _WA_ITALIC_RE.sub(r"*\1*", text)
    return text


def _split_discord(text: str, max_len: int = 1900) -> list[str]:
    """Split text into Discord-safe (<2000 char) chunks at paragraph boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).lstrip("\n") if current else para
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = para if len(para) <= max_len else para[:max_len]
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Rich embed card builder
# ---------------------------------------------------------------------------

_RATING_COLORS: dict[str, int] = {
    "BUY": 0x00C851,
    "OVERWEIGHT": 0x00897B,
    "HOLD": 0xFFBB33,
    "UNDERWEIGHT": 0xFF6D00,
    "SELL": 0xFF4444,
}
_UNCERTAINTY_COLOR = 0x9E9E9E

_RATING_EMOJIS: dict[str, str] = {
    "BUY": "🟢",
    "OVERWEIGHT": "🟩",
    "HOLD": "🟡",
    "UNDERWEIGHT": "🟠",
    "SELL": "🔴",
}


def build_embed_card(plan: "ConsensusPlan") -> discord.Embed:
    """Build a discord.Embed card from a ConsensusPlan."""
    rating = plan.final_rating.upper()
    color = (
        _UNCERTAINTY_COLOR
        if plan.confidence_score < 0.4
        else _RATING_COLORS.get(rating, _UNCERTAINTY_COLOR)
    )
    emoji = _RATING_EMOJIS.get(rating, "⚪")
    confidence_pct = int(plan.confidence_score * 100)

    embed = discord.Embed(
        title=f"{emoji} {plan.ticker} — {rating}",
        description=f"Analysis for {plan.trade_date} | **{confidence_pct}%** confidence",
        color=discord.Color(color),
    )

    entry = f"${plan.entry_price:.2f}" if plan.entry_price else "—"
    stop = f"${plan.stop_loss:.2f}" if plan.stop_loss else "—"
    target = f"${plan.price_target:.2f}" if plan.price_target else "—"
    embed.add_field(name="Entry", value=entry, inline=True)
    embed.add_field(name="Stop Loss", value=stop, inline=True)
    embed.add_field(name="Target", value=target, inline=True)

    if plan.entry_price and plan.stop_loss and plan.price_target and plan.stop_loss != plan.entry_price:
        risk = abs(plan.entry_price - plan.stop_loss)
        reward = abs(plan.price_target - plan.entry_price)
        rr = f"1:{reward / risk:.1f}"
    else:
        rr = "—"
    embed.add_field(name="Time Horizon", value=plan.time_horizon or "—", inline=True)
    embed.add_field(name="Risk/Reward", value=rr, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    if plan.executive_summary:
        embed.add_field(name="Summary", value=plan.executive_summary[:1024], inline=False)

    if plan.key_catalysts:
        embed.add_field(
            name="✅ Key Catalysts",
            value="\n".join(f"• {c}" for c in plan.key_catalysts[:3]),
            inline=True,
        )
    if plan.key_risks:
        embed.add_field(
            name="⚠️ Key Risks",
            value="\n".join(f"• {r}" for r in plan.key_risks[:3]),
            inline=True,
        )

    footer_parts = [f"Models: {plan.model_agreement}"]
    if plan.discovery_signals:
        footer_parts.append(f"Source: {', '.join(plan.discovery_signals)}")
    embed.set_footer(text=" | ".join(footer_parts))

    return embed


def build_session_summary_embed(
    plans: "list[ConsensusPlan]",
    date: str,
) -> discord.Embed:
    """Build end-of-session summary embed ranking all tickers by confidence."""
    _ORDER = ["BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL"]
    rating_counts: dict[str, int] = {}
    for p in plans:
        key = p.final_rating.upper()
        rating_counts[key] = rating_counts.get(key, 0) + 1

    count_str = " · ".join(
        f"{v} {k}"
        for k, v in sorted(
            rating_counts.items(),
            key=lambda x: _ORDER.index(x[0]) if x[0] in _ORDER else 99,
        )
    )

    embed = discord.Embed(
        title="📊 Daily Analysis Complete",
        description=f"{len(plans)} tickers analyzed | {count_str}",
        color=discord.Color(0x2196F3),
    )
    embed.set_footer(text=f"Date: {date}")

    sorted_plans = sorted(plans, key=lambda p: p.confidence_score, reverse=True)
    top_lines = [
        f"{i + 1}. **{p.ticker}** — {p.final_rating} ({int(p.confidence_score * 100)}%)"
        for i, p in enumerate(sorted_plans[:5])
    ]
    if top_lines:
        embed.add_field(name="Top Conviction", value="\n".join(top_lines), inline=False)

    return embed


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


def _is_authorised(user_id: int) -> bool:
    allowed = settings.discord_authorized_user_id_list
    if not allowed:
        return True  # open when not configured
    return str(user_id) in allowed


# ---------------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------------


class _TradingBotDiscord(discord.Client):

    async def on_ready(self) -> None:
        logger.info("Discord bot online: %s (id=%s)", self.user, self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages
        if message.author == self.user:
            return

        # Authorisation check
        if not _is_authorised(message.author.id):
            return

        body = message.content.strip()
        if not body:
            return

        lower = body.lower()

        # analyze command → run in background, push result back to same channel
        m = re.match(r"^analyze\s+(\S+)(?:\s+(\d{4}-\d{2}-\d{2}))?$", body, re.IGNORECASE)
        if m:
            ticker = m.group(1).upper()
            analysis_date = m.group(2) or date.today().strftime("%Y-%m-%d")
            await message.channel.send(
                _fmt(f"🔍 Analysing *{ticker}* for {analysis_date}…\nResults coming shortly.")
            )
            asyncio.create_task(
                _bg_discord_analyze(message.channel, ticker, analysis_date)
            )
            return

        # All other commands → delegate to the shared command handler
        from app.handlers.command_handler import handle_message  # lazy to avoid circular
        reply = await handle_message(str(message.author.id), body, skip_auth=True)
        for chunk in _split_discord(_fmt(reply)):
            await message.channel.send(chunk)


# ---------------------------------------------------------------------------
# Background analysis task (Discord path)
# ---------------------------------------------------------------------------


async def _bg_discord_analyze(
    channel: discord.TextChannel,
    ticker: str,
    analysis_date: str,
) -> None:
    """Run analysis and push results back to the Discord channel."""
    from app.db.session import get_db, save_analysis
    from app.services.trading_agent import analyze_stock
    from app.services.whatsapp import format_analysis_messages  # reuse formatter

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

    msgs = await format_analysis_messages(
        result["ticker"],
        result["date"],
        result["decision"],
        result["short_summary"],
        rich=result.get("rich"),
    )
    for msg in msgs:
        for chunk in _split_discord(_fmt(msg)):
            await channel.send(chunk)


# ---------------------------------------------------------------------------
# Public send helpers
# ---------------------------------------------------------------------------


_bot: _TradingBotDiscord | None = None


async def send_to_channel(body: str) -> None:
    """Send *body* to the configured broadcast channel (if bot is running)."""
    if not _bot or not settings.discord_channel_id:
        return
    channel = _bot.get_channel(settings.discord_channel_id)
    if channel is None:
        logger.warning("Discord channel %s not found – is the bot in that server?", settings.discord_channel_id)
        return
    for chunk in _split_discord(_fmt(body)):
        await channel.send(chunk)


async def send_analysis_embed(plan: "ConsensusPlan") -> None:
    """Send a rich embed card for one ticker to the broadcast channel."""
    if not _bot or not settings.discord_channel_id:
        return
    channel = _bot.get_channel(settings.discord_channel_id)
    if channel is None:
        logger.warning("Discord channel %s not found", settings.discord_channel_id)
        return
    try:
        embed = build_embed_card(plan)
        await channel.send(embed=embed)
    except Exception as exc:
        logger.warning("send_analysis_embed failed for %s: %s", plan.ticker, exc)


async def send_session_summary(plans: "list[ConsensusPlan]", date: str) -> None:
    """Send end-of-session ranked summary embed."""
    if not _bot or not settings.discord_channel_id:
        return
    channel = _bot.get_channel(settings.discord_channel_id)
    if channel is None:
        return
    try:
        embed = build_session_summary_embed(plans, date)
        await channel.send(embed=embed)
    except Exception as exc:
        logger.warning("send_session_summary failed: %s", exc)


async def broadcast_discord_analysis_card(
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str,
    rich: dict | None = None,
) -> None:
    """Broadcast a full analysis card to the Discord notification channel."""
    if not _bot or not settings.discord_channel_id:
        return
    from app.services.whatsapp import format_analysis_messages  # reuse formatter

    msgs = await format_analysis_messages(ticker, analysis_date, decision, short_summary, rich)
    for msg in msgs:
        await send_to_channel(msg)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

_bot_task: asyncio.Task | None = None


async def start_discord_bot() -> None:
    """Create the Discord client and connect (non-blocking, same event loop)."""
    global _bot, _bot_task

    if not settings.discord_bot_token:
        logger.info("DISCORD_BOT_TOKEN not set – Discord integration disabled")
        return

    intents = discord.Intents.default()
    intents.message_content = True  # privileged intent – enable in Developer Portal

    _bot = _TradingBotDiscord(intents=intents)
    _bot_task = asyncio.create_task(_bot.start(settings.discord_bot_token))
    logger.info("Discord bot task started")


async def stop_discord_bot() -> None:
    """Gracefully shut down the Discord client."""
    global _bot, _bot_task
    if _bot:
        await _bot.close()
        _bot = None
    if _bot_task:
        _bot_task.cancel()
        _bot_task = None
    logger.info("Discord bot stopped")
