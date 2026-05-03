"""Natural language chatbot agent for Discord.

Uses LangGraph's ReAct agent with MemorySaver checkpointer so each user
gets persistent multi-turn conversation history (keyed by Discord user ID).
Send "reset" or "new chat" to start a fresh session.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a smart, concise trading bot assistant. Help users make informed investment decisions.

You have these tools:
- analyze_stock_tool: Full AI analysis for a stock — use for "should I buy X?", "analyze NVDA", "what do you think about X?"
- screen_trending_stocks_tool: Find trending stocks in SP500 or NASDAQ100 — use for "what's hot today?", "trending stocks"
- get_stock_news_tool: Recent news headlines for a ticker
- get_technical_analysis_tool: Live current price, SMA20/SMA50, RSI, support/resistance, entry zone, breakout level
- get_watchlist_tool: Show the current watchlist
- add_to_watchlist_tool: Add a ticker to the daily watchlist
- remove_from_watchlist_tool: Remove a ticker from the watchlist
- get_bot_status_tool: Bot status and next scheduled run

Guidelines:
- Always use the appropriate tool before answering stock-specific questions
- Be concise and actionable — give a clear recommendation with reasoning
- For buy/sell questions, run analyze_stock_tool and summarise the key decision
- For entry point, current price, support/resistance, target, stop-loss, pullback, breakout, or any question asking what price to wait for, ALWAYS call get_technical_analysis_tool before answering
- If asked about technical signals, use get_technical_analysis_tool
- Never give numeric entry, target, or stop levels from analyze_stock_tool alone; verify with get_technical_analysis_tool and prefer the live price data when they conflict
- If the user first asks for an entry price and then replies only with a ticker, treat that as a continuation of the entry-point question and use get_technical_analysis_tool
- For news, use get_stock_news_tool
- Keep responses under 800 words unless detailed analysis is explicitly requested
- Remember previous messages in this conversation and build on them
"""

# Reset phrases that start a fresh session
_RESET_PHRASES = {"reset", "new chat", "new session", "clear", "start over", "/reset", "/new"}

_agent = None
_checkpointer = None

# Per-user session counters — incrementing starts a new thread_id
_session_counters: dict[str, int] = {}


def _get_agent():
    """Lazy-initialize and cache the ReAct agent with memory checkpointer."""
    global _agent, _checkpointer
    if _agent is not None:
        return _agent

    from app.agents.chatbot.tools import (
        add_to_watchlist_tool,
        analyze_stock_tool,
        get_bot_status_tool,
        get_stock_news_tool,
        get_technical_analysis_tool,
        get_watchlist_tool,
        remove_from_watchlist_tool,
        screen_trending_stocks_tool,
    )
    from app.config import settings

    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
        os.environ.setdefault("GEMINI_API_KEY", settings.google_api_key)

    from langchain_google_genai import ChatGoogleGenerativeAI
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.prebuilt import create_react_agent

    tools = [
        analyze_stock_tool,
        screen_trending_stocks_tool,
        get_stock_news_tool,
        get_technical_analysis_tool,
        get_watchlist_tool,
        add_to_watchlist_tool,
        remove_from_watchlist_tool,
        get_bot_status_tool,
    ]

    llm = ChatGoogleGenerativeAI(
        model=settings.analysis_model,
        google_api_key=settings.google_api_key,
        temperature=0.1,
    )

    _checkpointer = MemorySaver()
    _agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=_SYSTEM_PROMPT,
        checkpointer=_checkpointer,
    )
    logger.info("Chatbot agent initialised with model %s (memory enabled)", settings.analysis_model)
    return _agent


def _thread_id(user_id: str) -> str:
    """Return the current thread ID for a user."""
    counter = _session_counters.get(user_id, 0)
    return f"{user_id}:{counter}"


def reset_session(user_id: str) -> None:
    """Start a fresh conversation for this user by bumping their session counter."""
    _session_counters[user_id] = _session_counters.get(user_id, 0) + 1
    logger.info("Session reset for user %s → thread %s", user_id, _thread_id(user_id))


def _extract_text(content) -> str:
    """Extract plain text from a message content that may be a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content) if content else ""


async def chat(message: str, user_id: Optional[str] = None) -> str:
    """
    Process a natural-language message and return a response.

    If user_id is provided, conversation history is maintained across calls
    (multi-turn). Send a reset phrase to start a new session.
    """
    import asyncio

    from langchain_core.messages import HumanMessage

    # Check for reset intent before doing anything
    if user_id and message.strip().lower() in _RESET_PHRASES:
        reset_session(user_id)
        return "🔄 Session reset. Starting a fresh conversation — what would you like to know?"

    try:
        agent = _get_agent()

        config = (
            {"configurable": {"thread_id": _thread_id(user_id)}}
            if user_id
            else {}
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )

        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            return _extract_text(content) or "I couldn't generate a response. Please try again."

        return "I couldn't generate a response. Please try again."

    except Exception as exc:
        logger.exception("Chatbot agent error: %s", exc)
        return f"Sorry, I encountered an error: {str(exc)[:300]}"
