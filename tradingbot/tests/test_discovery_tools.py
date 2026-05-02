import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


def test_screen_volume_anomalies_flags_high_volume():
    universe = ["AAPL", "MSFT", "NVDA"]
    # Build a mock MultiIndex DataFrame that yf.download returns
    vol_data = {
        "AAPL": [100.0] * 30 + [500.0],  # 5x spike
        "MSFT": [100.0] * 31,              # no anomaly
        "NVDA": [100.0] * 30 + [250.0],   # 2.5x spike
    }
    mock_volume = pd.DataFrame(vol_data)
    mock_data = MagicMock()
    mock_data.__getitem__ = MagicMock(side_effect=lambda key: mock_volume if key == "Volume" else MagicMock())

    with patch("app.agents.discovery.tools.yf.download", return_value=mock_data):
        from app.agents.discovery.tools import screen_volume_anomalies
        results = screen_volume_anomalies(universe, threshold=2.0)

    tickers = [r["ticker"] for r in results]
    assert "AAPL" in tickers
    assert "NVDA" in tickers
    assert "MSFT" not in tickers


def test_screen_volume_anomalies_returns_empty_on_empty_universe():
    from app.agents.discovery.tools import screen_volume_anomalies
    assert screen_volume_anomalies([]) == []


def test_screen_volume_anomalies_returns_empty_on_exception():
    with patch("app.agents.discovery.tools.yf.download", side_effect=Exception("network error")):
        from app.agents.discovery.tools import screen_volume_anomalies
        assert screen_volume_anomalies(["AAPL"]) == []


def test_detect_breakout_returns_none_on_insufficient_data():
    mock_data = MagicMock()
    short_series = pd.Series([100.0] * 5)
    mock_data.__getitem__ = MagicMock(side_effect=lambda k: short_series)
    mock_data.__getitem__.return_value = short_series

    with patch("app.agents.discovery.tools.yf.download", return_value=mock_data):
        from app.agents.discovery.tools import detect_breakout
        # len(close) < 20 → None
        result = detect_breakout("AAPL")
    assert result is None


def test_load_universe_custom():
    from app.config import Settings
    with patch("app.agents.discovery.tools.settings", Settings(
        discovery_universe="custom",
        discovery_custom_universe="AAPL,MSFT"
    )):
        # Clear cache
        import app.agents.discovery.tools as tools_mod
        tools_mod._universe_cache.clear()
        result = tools_mod.load_universe()
    assert result == ["AAPL", "MSFT"]
