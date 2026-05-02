import discord
from app.agents.ensemble.schemas import ConsensusPlan
from app.services.discord_service import build_embed_card, build_session_summary_embed


def _plan(**kwargs) -> ConsensusPlan:
    defaults = dict(
        ticker="NVDA", trade_date="2026-05-02",
        final_rating="BUY", confidence_score=0.75,
        model_agreement="Both: BUY", time_horizon="2-4 weeks",
        executive_summary="Strong AI chip demand.",
        key_catalysts=["Q2 beat", "New GPU launch"],
        key_risks=["Rate hike fears"],
        entry_price=892.0, stop_loss=845.0, price_target=980.0,
    )
    return ConsensusPlan(**{**defaults, **kwargs})


def test_buy_embed_is_green():
    embed = build_embed_card(_plan(final_rating="BUY", confidence_score=0.75))
    assert embed.color.value == 0x00C851


def test_sell_embed_is_red():
    embed = build_embed_card(_plan(final_rating="SELL", confidence_score=0.75))
    assert embed.color.value == 0xFF4444


def test_hold_embed_is_yellow():
    embed = build_embed_card(_plan(final_rating="HOLD", confidence_score=0.75))
    assert embed.color.value == 0xFFBB33


def test_low_confidence_is_gray():
    embed = build_embed_card(_plan(final_rating="BUY", confidence_score=0.3))
    assert embed.color.value == 0x9E9E9E


def test_title_contains_ticker_and_rating():
    embed = build_embed_card(_plan())
    assert "NVDA" in embed.title
    assert "BUY" in embed.title


def test_has_price_fields():
    embed = build_embed_card(_plan())
    field_names = [f.name for f in embed.fields]
    assert "Entry" in field_names
    assert "Stop Loss" in field_names
    assert "Target" in field_names


def test_discovery_signals_in_footer():
    embed = build_embed_card(_plan(discovery_signals=["volume_spike", "news_active"]))
    assert "volume_spike" in embed.footer.text


def test_no_discovery_signals_footer_only_has_models():
    embed = build_embed_card(_plan(discovery_signals=[]))
    assert "Models:" in embed.footer.text
    assert "Source:" not in embed.footer.text


def test_session_summary_description_has_count():
    plans = [
        _plan(final_rating="BUY"),
        _plan(final_rating="BUY"),
        _plan(final_rating="HOLD"),
        _plan(final_rating="SELL"),
    ]
    embed = build_session_summary_embed(plans, "2026-05-02")
    assert "4 tickers" in embed.description


def test_session_summary_top_conviction_sorted():
    plans = [
        _plan(ticker="AAPL", final_rating="HOLD", confidence_score=0.5),
        _plan(ticker="NVDA", final_rating="BUY", confidence_score=1.0),
    ]
    embed = build_session_summary_embed(plans, "2026-05-02")
    field = next(f for f in embed.fields if f.name == "Top Conviction")
    # NVDA should be listed first (higher confidence)
    assert field.value.index("NVDA") < field.value.index("AAPL")
