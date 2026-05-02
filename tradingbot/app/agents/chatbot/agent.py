"""Natural language chatbot agent for Discord.

Uses LangGraph's ReAct agent with a set of trading tools to answer
free-form questions about stocks, trending markets, and watchlist management.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a smart, concise trading bot assistant. Help users make informed investment decisions.

You have these tools:
- analyze_stock_tool: Full AI analysis for a stock — use for "should I buy X?", "analyze NVDA", "what do you think about X?"
- screen_trending_stocks_tool: Find trending stocks in SP500 or NASDAQ100 — use for "what's hot today?", "trending stocks"
- get_stock_news_tool: Recent news headlines for a ticker
- get_technical_analysis_tool: RSI, SMA20, breakout signals for a ticker
- get_watchlist_tool: Show the current watchlist
- add_to_watchlist_tool: Add a ticker to the daily watchlist
- remove_from_watchlist_tool: Remove a ticker from the watchlist
- get_bot_status_tool: Bot status and next scheduled run

Guidelines:
- Always use the appropriate tool before answering stock-specific questions
- Be concise and actionable — give a clear recommendation with reasoning
- For buy/sell questions, run analyze_stock_tool and summarise the key decision
- If asked about technical signals, use get_technical_analysis_tool
- For news, use get_stock_news_tool
- Keep responses under 800 words unless detailed analysis is explicitly requested
"""

_agent = None
_agent_lock: "asyncio.Lock | None" = None


def _get_agent():
    """Lazy-initialize and cache the ReAct agent."""
    global _agent
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

    # Ensure API keys are in os.environ for LangChain clients
    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)
        os.environ.setdefault("GEMINI_API_KEY", settings.google_api_key)

    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI
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

    _agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=_SYSTEM_PROMPT,
    )
    logger.info("Chatbot agent initialised with model %s", settings.analysis_model)
    return _agent


async def chat(message: str) -> str:
    """Process a natural-language message and return a response string."""
    import asyncio

    from langchain_core.messages import HumanMessage

    global _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()

    try:
        async with _agent_lock:
            agent = _get_agent()

        result = await agent.ainvoke({"messages": [HumanMessage(content=message)]})

        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            if content:
                return str(content)

        return "I couldn't generate a response. Please try again."

    except Exception as exc:
        logger.exception("Chatbot agent error: %s", exc)
        return f"Sorry, I encountered an error: {str(exc)[:300]}"
