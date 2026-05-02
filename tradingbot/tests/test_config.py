from app.config import Settings


def _clean_settings(**overrides):
    """Create Settings with no .env file loading."""
    return Settings(_env_file=None, **overrides)


def test_new_settings_have_defaults():
    s = _clean_settings()
    assert s.analysis_model == "gemini-2.5-pro"
    assert s.discovery_enabled is False
    assert s.discovery_universe == "sp500"
    assert s.discovery_max_tickers == 10
    assert s.discovery_custom_universe_list == []


def test_discovery_custom_universe_list():
    s = _clean_settings(discovery_custom_universe="AAPL,MSFT, NVDA ")
    assert s.discovery_custom_universe_list == ["AAPL", "MSFT", "NVDA"]


def test_discovery_custom_universe_list_single_ticker():
    s = _clean_settings(discovery_custom_universe="AAPL")
    assert s.discovery_custom_universe_list == ["AAPL"]


def test_discovery_custom_universe_list_empty_default():
    s = _clean_settings()
    assert s.discovery_custom_universe_list == []
