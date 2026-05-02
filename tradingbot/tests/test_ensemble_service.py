"""Tests for the single-phase daily scheduler job."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_daily_job_empty_watchlist_sends_message():
    """Job sends a notification when watchlist is empty and discovery is off."""
    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.get_db", MagicMock()),
        patch("app.services.scheduler.get_watchlist", return_value=[]),
        patch("app.services.scheduler.save_analysis"),
        patch("app.services.scheduler.send_to_channel", new_callable=AsyncMock) as mock_send,
        patch("app.services.scheduler.broadcast", new_callable=AsyncMock),
        patch("app.services.scheduler.send_analysis_embed", new_callable=AsyncMock),
        patch("app.services.scheduler.send_session_summary", new_callable=AsyncMock),
    ):
        mock_settings.discovery_enabled = False
        mock_settings.analysis_model = "gemini-2.5-pro"

        from app.services.scheduler import _daily_job
        await _daily_job()

    assert mock_send.called
    msg = mock_send.call_args[0][0].lower()
    assert "empty" in msg or "nothing" in msg


@pytest.mark.asyncio
async def test_daily_job_analyses_watchlist_stocks():
    """Job calls analyze_stock for each ticker and sends an embed."""
    mock_stock = MagicMock()
    mock_stock.ticker = "NVDA"

    mock_result = {
        "ticker": "NVDA",
        "date": "2026-05-02",
        "decision": "BUY",
        "short_summary": "Strong AI demand.",
        "full_report": "Full report.",
        "success": True,
        "error": None,
        "rich": {},
    }

    mock_analyze = AsyncMock(return_value=mock_result)

    with (
        patch("app.services.scheduler.settings") as mock_settings,
        patch("app.services.scheduler.get_db", MagicMock()),
        patch("app.services.scheduler.get_watchlist", return_value=[mock_stock]),
        patch("app.services.scheduler.save_analysis"),
        patch("app.services.scheduler.analyze_stock", mock_analyze),
        patch("app.services.scheduler.send_to_channel", new_callable=AsyncMock),
        patch("app.services.scheduler.broadcast", new_callable=AsyncMock),
        patch("app.services.scheduler.send_analysis_embed", new_callable=AsyncMock),
        patch("app.services.scheduler.send_session_summary", new_callable=AsyncMock),
    ):
        mock_settings.discovery_enabled = False
        mock_settings.analysis_model = "gemini-2.5-pro"

        from app.services.scheduler import _daily_job
        await _daily_job()

    mock_analyze.assert_called_once()
    call_args = mock_analyze.call_args
    assert call_args[0][0] == "NVDA"
    assert call_args[1]["model"] == "gemini-2.5-pro"
