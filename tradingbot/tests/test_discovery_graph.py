import pytest
from unittest.mock import patch
from app.agents.discovery.judge import discovery_judge_node


def _state_with_candidates():
    return {
        "universe": ["AAPL", "MSFT", "NVDA", "TSLA"],
        "discovery_date": "2026-05-02",
        "volume_candidates": [
            {"ticker": "NVDA", "confluence_score": 1.0, "signals": ["volume_spike"], "priority": "HIGH"},
            {"ticker": "AAPL", "confluence_score": 1.0, "signals": ["volume_spike"], "priority": "LOW"},
        ],
        "news_candidates": [
            {"ticker": "NVDA", "confluence_score": 1.0, "signals": ["news_active"], "priority": "HIGH"},
            {"ticker": "TSLA", "confluence_score": 1.0, "signals": ["news_active"], "priority": "MEDIUM"},
        ],
        "technical_candidates": [
            {"ticker": "NVDA", "confluence_score": 1.0, "signals": ["above_sma20"], "priority": "HIGH"},
        ],
        "discovery_result": None,
        "selected_tickers": [],
    }


def test_judge_scores_confluence_correctly():
    result = discovery_judge_node(_state_with_candidates())
    assert result["selected_tickers"][0] == "NVDA"


def test_judge_deduplicates_and_merges_signals():
    result = discovery_judge_node(_state_with_candidates())
    dr = result["discovery_result"]
    nvda = next(c for c in dr["candidates"] if c["ticker"] == "NVDA")
    assert nvda["confluence_score"] == 3.0
    assert nvda["priority"] == "HIGH"
    assert "volume_spike" in nvda["signals"]
    assert "news_active" in nvda["signals"]
    assert "above_sma20" in nvda["signals"]


def test_judge_respects_max_tickers():
    with patch("app.agents.discovery.judge.settings") as mock_settings:
        mock_settings.discovery_max_tickers = 1
        result = discovery_judge_node(_state_with_candidates())
    assert len(result["selected_tickers"]) == 1


def test_judge_handles_empty_candidates():
    state = {
        "universe": ["AAPL"],
        "discovery_date": "2026-05-02",
        "volume_candidates": [],
        "news_candidates": [],
        "technical_candidates": [],
        "discovery_result": None,
        "selected_tickers": [],
    }
    result = discovery_judge_node(state)
    assert result["selected_tickers"] == []


def test_graph_compiles():
    from app.agents.discovery.graph import _build_graph
    graph = _build_graph()
    assert graph is not None
