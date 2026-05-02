from __future__ import annotations

import logging

from app.agents.discovery.schemas import DiscoveryState
from app.config import settings

logger = logging.getLogger(__name__)


def discovery_judge_node(state: DiscoveryState) -> dict:
    """Aggregate all screener candidates, score confluence, return ranked top N."""
    score_map: dict[str, dict] = {}

    all_lists = [
        state.get("volume_candidates", []),
        state.get("news_candidates", []),
        state.get("technical_candidates", []),
    ]

    for candidate_list in all_lists:
        for c in candidate_list:
            ticker = c["ticker"]
            if ticker not in score_map:
                score_map[ticker] = {
                    "ticker": ticker,
                    "confluence_score": 0.0,
                    "signals": [],
                    "priority": "LOW",
                }
            score_map[ticker]["confluence_score"] += 1.0
            score_map[ticker]["signals"].extend(c.get("signals", []))

    for entry in score_map.values():
        entry["signals"] = list(dict.fromkeys(entry["signals"]))
        score = entry["confluence_score"]
        if score >= 3:
            entry["priority"] = "HIGH"
        elif score >= 2:
            entry["priority"] = "MEDIUM"

    sorted_candidates = sorted(
        score_map.values(), key=lambda x: x["confluence_score"], reverse=True
    )
    top = sorted_candidates[: settings.discovery_max_tickers]
    top_tickers = [c["ticker"] for c in top]

    logger.info(
        "Discovery judge: %d unique candidates → top %d: %s",
        len(sorted_candidates), len(top_tickers), top_tickers,
    )

    return {
        "discovery_result": {
            "candidates": sorted_candidates,
            "top_tickers": top_tickers,
        },
        "selected_tickers": top_tickers,
    }
