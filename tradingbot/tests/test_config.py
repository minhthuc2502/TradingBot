from app.config import Settings


def test_new_settings_have_defaults():
    s = Settings()
    assert s.gemini_pro_model == "gemini-2.5-pro"
    assert s.gemini_flash_model == "gemini-2.0-flash"
    assert s.discovery_enabled is True
    assert s.discovery_universe == "sp500"
    assert s.discovery_max_tickers == 10
    assert s.discovery_time == "23:00"


def test_discovery_custom_universe_list():
    s = Settings(discovery_custom_universe="AAPL,MSFT, NVDA ")
    assert s.discovery_custom_universe_list == ["AAPL", "MSFT", "NVDA"]
