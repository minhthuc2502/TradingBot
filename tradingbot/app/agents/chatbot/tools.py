"""LangChain tools for the Discord chatbot agent."""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import date as date_type
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def analyze_stock_tool(ticker: str, analysis_date: Optional[str] = None) -> str:
    """Run a comprehensive AI stock analysis using TradingAgents multi-agent system.

    Args:
        ticker: Stock ticker symbol (e.g. NVDA, AAPL, AMZN)
        analysis_date: Optional date in YYYY-MM-DD format; defaults to today
    """
    from app.agents.discovery.tools import get_technical_snapshot
    from app.config import settings
    from app.services.trading_agent import analyze_stock

    ticker = ticker.upper().strip()
    if analysis_date is None:
        analysis_date = date_type.today().strftime("%Y-%m-%d")

    result = await analyze_stock(ticker, analysis_date, model=settings.analysis_model)

    if not result["success"]:
        return f"Analysis failed for {ticker}: {result.get('error', 'Unknown error')}"

    rich = result.get("rich", {})
    portfolio_decision = rich.get("final_trade_decision", result["full_report"])
    loop = asyncio.get_event_loop()
    snapshot = await loop.run_in_executor(
        None, functools.partial(get_technical_snapshot, ticker)
    )

    market_context = ""
    if snapshot:
        market_context = (
            f"Live market context: current price ${snapshot['current_price']:.2f}, "
            f"SMA20 ${snapshot['sma20']:.2f}, 20-day support ${snapshot['support_20d']:.2f}, "
            f"20-day resistance ${snapshot['resistance_20d']:.2f}. "
            f"For entry-point or price-level questions, use the live technical levels rather than any stale plan values in the narrative.\n\n"
        )

    return (
        f"**{ticker} Analysis ({analysis_date})**\n"
        f"Decision: **{result['decision']}**\n\n"
        f"{market_context}"
        f"{portfolio_decision[:2000]}"
    )


@tool
async def screen_trending_stocks_tool(universe: str = "sp500", top_n: int = 5) -> str:
    """Screen for trending / high-activity stocks in the SP500 or NASDAQ100.

    Args:
        universe: 'sp500' or 'nasdaq100' (default: sp500)
        top_n: Number of results to return (max 10)
    """
    from app.agents.discovery.tools import (
        get_news_active_tickers,
        load_universe,
        screen_volume_anomalies,
    )
    from app.config import settings

    top_n = min(max(top_n, 1), 10)

    universe_key = "nasdaq100" if "nasdaq" in universe.lower() else "sp500"

    # Temporarily patch settings.discovery_universe so load_universe() picks it up
    original = settings.discovery_universe
    object.__setattr__(settings, "discovery_universe", universe_key)
    try:
        loop = asyncio.get_event_loop()
        tickers = await loop.run_in_executor(None, load_universe)
        volume_results = await loop.run_in_executor(
            None, functools.partial(screen_volume_anomalies, tickers)
        )
        news_results = await loop.run_in_executor(
            None, functools.partial(get_news_active_tickers, tickers)
        )
    finally:
        object.__setattr__(settings, "discovery_universe", original)

    # Combine scores
    scores: dict[str, int] = {}
    for r in volume_results[:10]:
        t = r.get("ticker", "")
        if t:
            scores[t] = scores.get(t, 0) + 2
    for r in news_results[:10]:
        t = r.get("ticker", "")
        if t:
            scores[t] = scores.get(t, 0) + 1

    if not scores:
        return f"No trending stocks found in {universe_key.upper()} right now."

    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    lines = [f"{i + 1}. **{t}** (activity score: {s})" for i, (t, s) in enumerate(top)]
    return f"**Trending stocks in {universe_key.upper()}:**\n" + "\n".join(lines)


@tool
async def get_stock_news_tool(ticker: str) -> str:
    """Get recent news headlines for a specific stock.

    Args:
        ticker: Stock ticker symbol
    """
    import yfinance as yf

    ticker = ticker.upper().strip()
    try:
        loop = asyncio.get_event_loop()
        stock = await loop.run_in_executor(None, yf.Ticker, ticker)
        news = stock.news or []

        if not news:
            return f"No recent news found for {ticker}."

        lines = []
        for i, item in enumerate(news[:6], 1):
            title = item.get("title", "No title")
            publisher = item.get("publisher", "")
            suffix = f" — {publisher}" if publisher else ""
            lines.append(f"{i}. {title}{suffix}")

        return f"**Recent news for {ticker}:**\n" + "\n".join(lines)
    except Exception as exc:
        return f"Could not fetch news for {ticker}: {exc}"


@tool
async def get_technical_analysis_tool(ticker: str) -> str:
    """Get technical analysis signals (SMA20, RSI, breakout) for a stock.

    Args:
        ticker: Stock ticker symbol
    """
    from app.agents.discovery.tools import detect_breakout, get_technical_snapshot

    ticker = ticker.upper().strip()
    try:
        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(
            None, functools.partial(get_technical_snapshot, ticker)
        )
        if not snapshot:
            return f"No data available for {ticker}."

        signal = await loop.run_in_executor(
            None, functools.partial(detect_breakout, ticker)
        )

        current_price = snapshot["current_price"]
        sma20 = snapshot["sma20"]
        sma50 = snapshot.get("sma50")
        rsi14 = snapshot.get("rsi14")
        support_20d = snapshot["support_20d"]
        resistance_20d = snapshot["resistance_20d"]
        pct_from_sma20 = snapshot["pct_from_sma20"]
        entry_zone_low = snapshot["entry_zone_low"]
        entry_zone_high = snapshot["entry_zone_high"]
        atr14 = snapshot.get("atr14")
        signals = signal.get("signals", []) if signal else []
        signals_str = ", ".join(signals) if signals else "none"

        if pct_from_sma20 >= 2.0:
            entry_plan = (
                f"Wait for a pullback toward SMA20 at ${sma20:.2f}. "
                f"Best watch zone: ${entry_zone_low:.2f}-${entry_zone_high:.2f}."
            )
        elif pct_from_sma20 >= -1.0:
            entry_plan = (
                f"Price is already near the SMA20 watch area. "
                f"Watch for support to hold in ${entry_zone_low:.2f}-${entry_zone_high:.2f} before entering."
            )
        else:
            entry_plan = (
                f"Price is trading below SMA20, so wait for reclaim or stabilization near "
                f"${entry_zone_low:.2f}-${entry_zone_high:.2f} before entering."
            )

        lines = [
            f"**Technical Analysis for {ticker}:**",
            f"Current price: ${current_price:.2f} ({snapshot['day_change_pct']:+.2f}% today)",
            f"SMA20: ${sma20:.2f} | SMA50: {f'${sma50:.2f}' if sma50 is not None else 'N/A'}",
            f"RSI14: {rsi14 if rsi14 is not None else 'N/A'} | ATR14: {f'${atr14:.2f}' if atr14 is not None else 'N/A'}",
            f"20-day support/resistance: ${support_20d:.2f} / ${resistance_20d:.2f}",
            f"Distance from SMA20: {pct_from_sma20:+.2f}%",
            f"Potential entry watch price: ${sma20:.2f}",
            f"Entry zone: ${entry_zone_low:.2f}-${entry_zone_high:.2f}",
            f"Breakout trigger: close above ${resistance_20d:.2f}",
            f"Signals: {signals_str}",
            f"Entry view: {entry_plan}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Could not get technical analysis for {ticker}: {exc}"


@tool
def get_watchlist_tool() -> str:
    """Get the current stock watchlist."""
    from app.db.session import get_db, get_watchlist

    with get_db() as db:
        stocks = get_watchlist(db)
    if not stocks:
        return "The watchlist is empty."
    tickers = [s.ticker for s in stocks]
    return f"**Current watchlist ({len(tickers)} stocks):** {', '.join(tickers)}"


@tool
def add_to_watchlist_tool(ticker: str) -> str:
    """Add a stock to the watchlist for daily analysis.

    Args:
        ticker: Stock ticker symbol to add
    """
    from app.db.session import add_stock, get_db, stock_exists

    ticker = ticker.upper().strip()
    with get_db() as db:
        if stock_exists(db, ticker):
            return f"**{ticker}** is already in the watchlist."
        add_stock(db, ticker, added_by="discord_chatbot")
    return f"✅ **{ticker}** added to the watchlist."


@tool
def remove_from_watchlist_tool(ticker: str) -> str:
    """Remove a stock from the watchlist.

    Args:
        ticker: Stock ticker symbol to remove
    """
    from app.db.session import get_db, remove_stock

    ticker = ticker.upper().strip()
    with get_db() as db:
        removed = remove_stock(db, ticker)
    return (
        f"✅ **{ticker}** removed from the watchlist."
        if removed
        else f"**{ticker}** was not in the watchlist."
    )


@tool
def get_bot_status_tool() -> str:
    """Get the trading bot's current status, next scheduled run, and watchlist size."""
    from app.config import settings
    from app.db.session import get_config, get_db, get_watchlist
    from app.services.scheduler import next_run_info

    with get_db() as db:
        stock_count = len(get_watchlist(db))
        analysis_time = get_config(db, "analysis_time", settings.analysis_time)
        timezone = get_config(db, "analysis_timezone", settings.analysis_timezone)

    return (
        f"**TradingBot Status** ✅\n"
        f"Watchlist: {stock_count} stocks\n"
        f"Daily analysis: {analysis_time} ({timezone})\n"
        f"Next run: {next_run_info()}\n"
        f"Model: {settings.analysis_model}"
    )
