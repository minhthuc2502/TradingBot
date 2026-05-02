from __future__ import annotations

import asyncio
import logging
from typing import List

from langgraph.graph import END, START, StateGraph

from app.agents.discovery.analysts import (
    news_scanner_node,
    technical_screener_node,
    volume_analyst_node,
)
from app.agents.discovery.judge import discovery_judge_node
from app.agents.discovery.schemas import DiscoveryState
from app.agents.discovery.tools import load_universe

logger = logging.getLogger(__name__)

_compiled_graph = None


def _build_graph():
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    g = StateGraph(DiscoveryState)
    g.add_node("volume_analyst", volume_analyst_node)
    g.add_node("news_scanner", news_scanner_node)
    g.add_node("technical_screener", technical_screener_node)
    g.add_node("discovery_judge", discovery_judge_node)

    g.add_edge(START, "volume_analyst")
    g.add_edge("volume_analyst", "news_scanner")
    g.add_edge("news_scanner", "technical_screener")
    g.add_edge("technical_screener", "discovery_judge")
    g.add_edge("discovery_judge", END)

    _compiled_graph = g.compile()
    return _compiled_graph


def _run_discovery_sync(universe: List[str], date: str) -> List[str]:
    graph = _build_graph()
    initial: DiscoveryState = {
        "universe": universe,
        "discovery_date": date,
        "volume_candidates": [],
        "news_candidates": [],
        "technical_candidates": [],
        "discovery_result": None,
        "selected_tickers": [],
    }
    final_state = graph.invoke(initial)
    return final_state.get("selected_tickers", [])


async def run_discovery(date: str) -> List[str]:
    """Run the full discovery pipeline. Returns selected tickers or [] on error."""
    try:
        universe = load_universe()
        if not universe:
            logger.warning("Discovery: empty universe, skipping")
            return []
        logger.info("Discovery starting for %d tickers on %s", len(universe), date)
        loop = asyncio.get_event_loop()
        tickers = await loop.run_in_executor(None, _run_discovery_sync, universe, date)
        logger.info("Discovery complete: %s", tickers)
        return tickers
    except Exception as exc:
        logger.exception("Discovery graph failed: %s", exc)
        return []
