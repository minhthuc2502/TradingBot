from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_analyze_stock_tool_includes_live_market_context():
    mock_result = {
        "success": True,
        "decision": "BUY",
        "full_report": "Entry: $155\nTarget: $175\nStop-Loss: $145",
        "rich": {"final_trade_decision": "Entry: $155\nTarget: $175\nStop-Loss: $145"},
    }
    mock_snapshot = {
        "current_price": 360.0,
        "sma20": 342.5,
        "support_20d": 330.0,
        "resistance_20d": 366.0,
    }

    with patch("app.services.trading_agent.analyze_stock", new=AsyncMock(return_value=mock_result)):
        with patch("app.agents.discovery.tools.get_technical_snapshot", return_value=mock_snapshot):
            from app.agents.chatbot.tools import analyze_stock_tool

            result = await analyze_stock_tool.ainvoke({"ticker": "AMD", "analysis_date": "2026-05-03"})

    assert "current price $360.00" in result
    assert "use the live technical levels" in result
    assert "Entry: $155" in result