"""Discord bot service.

Runs a discord.py bot inside the same asyncio event loop as FastAPI.
The bot listens for messages, routes them to a natural-language chatbot agent,
and broadcasts daily analysis results to a configured notification channel.

Setup (in the Discord Developer Portal)
----------------------------------------
1. Create an application + bot.
2. Under "Bot → Privileged Gateway Intents", enable *Message Content Intent*.
3. Invite the bot with scopes ``bot`` + permissions ``Send Messages``,
   ``Read Message History``, ``View Channels``.
4. Copy the bot token into ``DISCORD_BOT_TOKEN`` in your ``.env``.
5. Copy the notification channel ID into ``DISCORD_CHANNEL_ID``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import discord

from app.config import settings

if TYPE_CHECKING:
    from app.schemas import AnalysisPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Markdown conversion  (WhatsApp *bold* / _italic_ → Discord **bold** / *italic*)
# ---------------------------------------------------------------------------

_WA_BOLD_RE = re.compile(r"\*([^*\n]+)\*")
_WA_ITALIC_RE = re.compile(r"_([^_\n]+)_")


def _fmt(text: str) -> str:
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
    "STRONG BUY": 0x00C851,
    "OVERWEIGHT": 0x00897B,
    "HOLD": 0xFFBB33,
    "UNDERWEIGHT": 0xFF6D00,
    "SELL": 0xFF4444,
    "STRONG SELL": 0xFF4444,
}
_UNCERTAINTY_COLOR = 0x9E9E9E

_RATING_EMOJIS: dict[str, str] = {
    "BUY": "🟢",
    "STRONG BUY": "🟢",
    "OVERWEIGHT": "🟩",
    "HOLD": "🟡",
    "UNDERWEIGHT": "🟠",
    "SELL": "🔴",
    "STRONG SELL": "🔴",
}


def build_embed_card(plan: "AnalysisPlan") -> discord.Embed:
    """Build a discord.Embed card from an AnalysisPlan."""
    rating = plan.final_rating.upper()
    color = _RATING_COLORS.get(rating, _UNCERTAINTY_COLOR)
    emoji = _RATING_EMOJIS.get(rating, "⚪")

    embed = discord.Embed(
        title=f"{emoji} {plan.ticker} — {rating}",
        description=f"Analysis for {plan.trade_date}",
        color=discord.Color(color),
    )

    entry = f"${plan.entry_price:.2f}" if plan.entry_price else "—"
    stop = f"${plan.stop_loss:.2f}" if plan.stop_loss else "—"
    target = f"${plan.price_target:.2f}" if plan.price_target else "—"
    embed.add_field(name="Entry", value=entry, inline=True)
    embed.add_field(name="Stop Loss", value=stop, inline=True)
    embed.add_field(name="Target", value=target, inline=True)

    if plan.time_horizon:
        embed.add_field(name="Time Horizon", value=plan.time_horizon, inline=True)

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

    footer_parts = []
    if plan.model_agreement:
        footer_parts.append(f"Model: {plan.model_agreement}")
    if plan.discovery_signals:
        footer_parts.append(f"Source: {', '.join(plan.discovery_signals)}")
    if footer_parts:
        embed.set_footer(text=" | ".join(footer_parts))

    return embed


def build_session_summary_embed(
    plans: "list[AnalysisPlan]",
    date: str,
) -> discord.Embed:
    """Build end-of-session summary embed ranking all tickers by rating."""
    _ORDER = ["STRONG BUY", "BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL", "STRONG SELL"]
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

    buy_ratings = {"BUY", "STRONG BUY", "OVERWEIGHT"}
    top_buys = [p for p in plans if p.final_rating.upper() in buy_ratings]
    if top_buys:
        top_lines = [
            f"{i + 1}. **{p.ticker}** — {p.final_rating}"
            for i, p in enumerate(top_buys[:5])
        ]
        embed.add_field(name="Top Buys", value="\n".join(top_lines), inline=False)

    return embed


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------


def _is_authorised(user_id: int) -> bool:
    allowed = settings.discord_authorized_user_id_list
    if not allowed:
        return True
    return str(user_id) in allowed


# ---------------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------------


class _TradingBotDiscord(discord.Client):

    async def on_ready(self) -> None:
        logger.info("Discord bot online: %s (id=%s)", self.user, self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        if not _is_authorised(message.author.id):
            return

        body = message.content.strip()
        if not body:
            return

        # Route all messages through the natural-language chatbot agent
        asyncio.create_task(
            _handle_chatbot_message(message.channel, body, str(message.author.id))
        )


# ---------------------------------------------------------------------------
# Chatbot message handler
# ---------------------------------------------------------------------------


async def _handle_chatbot_message(
    channel: discord.TextChannel,
    message: str,
    user_id: str,
) -> None:
    """Run the chatbot agent and post the reply back to the channel."""
    from app.agents.chatbot.agent import chat

    try:
        async with channel.typing():
            reply = await chat(message, user_id=user_id)
        for chunk in _split_discord(reply):
            await channel.send(chunk)
    except Exception as exc:
        logger.exception("Chatbot handler error: %s", exc)
        await channel.send(f"❌ Sorry, something went wrong: {str(exc)[:200]}")


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
        logger.warning("Discord channel %s not found", settings.discord_channel_id)
        return
    for chunk in _split_discord(_fmt(body)):
        await channel.send(chunk)


async def send_analysis_embed(plan: "AnalysisPlan") -> None:
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


async def send_session_summary(plans: "list[AnalysisPlan]", date: str) -> None:
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
    intents.message_content = True

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
