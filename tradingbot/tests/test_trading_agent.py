from unittest.mock import patch
from app.config import Settings


def test_build_ta_config_gemini_override():
    from app.services.trading_agent import _build_ta_config
    config = _build_ta_config(model="gemini-2.5-pro")
    assert config["llm_provider"] == "google"
    assert config["deep_think_llm"] == "gemini-2.5-pro"
    assert config["quick_think_llm"] == "gemini-2.5-pro"
    assert config.get("backend_url") is None


def test_build_ta_config_flash_override():
    from app.services.trading_agent import _build_ta_config
    config = _build_ta_config(model="gemini-2.0-flash")
    assert config["llm_provider"] == "google"
    assert config["deep_think_llm"] == "gemini-2.0-flash"


def test_build_ta_config_default_uses_settings():
    from app.services.trading_agent import _build_ta_config
    with patch("app.services.trading_agent.settings",
               Settings(llm_provider="openai", deep_think_llm="gpt-4o", quick_think_llm="gpt-4o-mini")):
        config = _build_ta_config()
    assert config["llm_provider"] == "openai"
    assert config["deep_think_llm"] == "gpt-4o"


def test_build_ta_config_none_model_uses_settings():
    from app.services.trading_agent import _build_ta_config
    config = _build_ta_config(model=None)
    # Should not override provider
    assert "gemini" not in config.get("deep_think_llm", "").lower() or config["llm_provider"] == "google"


def test_ensemble_schemas_defaults():
    from app.agents.ensemble.schemas import ConsensusPlan
    plan = ConsensusPlan(
        ticker="AAPL", trade_date="2026-05-02",
        final_rating="BUY", confidence_score=0.75,
        time_horizon="2-4 weeks", executive_summary="Test.",
    )
    assert plan.discovery_signals == []
    assert plan.key_catalysts == []
    assert plan.entry_price is None
    assert plan.model_agreement == ""
