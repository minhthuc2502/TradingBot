import pytest
from unittest.mock import patch, MagicMock
from app.agents.discovery.schemas import DiscoveryState


def _base_state() -> DiscoveryState:
    return {
        "universe": ["AAPL", "MSFT", "NVDA"],
        "discovery_date": "2026-05-02",
        "volume_candidates": [],
        "news_candidates": [],
        "technical_candidates": [],
        "discovery_result": None,
        "selected_tickers": [],
    }


def test_volume_analyst_returns_candidates_on_data():
    mock_raw = [{"ticker": "NVDA", "volume_ratio": 3.5, "signal": "volume_spike"}]
    mock_llm_response = MagicMock()
    mock_llm_response.content = '[{"ticker": "NVDA", "confluence_score": 1.0, "signals": ["volume_spike"], "priority": "HIGH"}]'

    with patch("app.agents.discovery.analysts.screen_volume_anomalies", return_value=mock_raw), \
         patch("app.agents.discovery.analysts._get_discovery_llm") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_llm_response
        mock_factory.return_value = mock_llm

        from app.agents.discovery.analysts import volume_analyst_node
        result = volume_analyst_node(_base_state())

    assert "volume_candidates" in result
    assert result["volume_candidates"][0]["ticker"] == "NVDA"


def test_volume_analyst_returns_empty_on_no_data():
    with patch("app.agents.discovery.analysts.screen_volume_anomalies", return_value=[]):
        from app.agents.discovery.analysts import volume_analyst_node
        result = volume_analyst_node(_base_state())
    assert result["volume_candidates"] == []


def test_volume_analyst_falls_back_on_llm_failure():
    mock_raw = [{"ticker": "AAPL", "volume_ratio": 3.0, "signal": "volume_spike"}]
    with patch("app.agents.discovery.analysts.screen_volume_anomalies", return_value=mock_raw), \
         patch("app.agents.discovery.analysts._get_discovery_llm") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("API error")
        mock_factory.return_value = mock_llm

        from app.agents.discovery.analysts import volume_analyst_node
        result = volume_analyst_node(_base_state())

    # Fallback: rule-based candidates from raw data
    assert len(result["volume_candidates"]) >= 1
    assert result["volume_candidates"][0]["ticker"] == "AAPL"


def test_technical_screener_runs_on_prior_candidates():
    state = _base_state()
    state["volume_candidates"] = [{"ticker": "AAPL", "confluence_score": 1.0, "signals": [], "priority": "LOW"}]
    mock_breakout = {"ticker": "AAPL", "signals": ["above_sma20"], "rsi": 68.0, "signal": "technical_setup"}

    with patch("app.agents.discovery.analysts.detect_breakout", return_value=mock_breakout):
        from app.agents.discovery.analysts import technical_screener_node
        result = technical_screener_node(state)

    assert any(c["ticker"] == "AAPL" for c in result["technical_candidates"])


def test_technical_screener_returns_empty_on_no_breakouts():
    with patch("app.agents.discovery.analysts.detect_breakout", return_value=None):
        from app.agents.discovery.analysts import technical_screener_node
        result = technical_screener_node(_base_state())
    assert result["technical_candidates"] == []
