import pytest
from unittest.mock import AsyncMock, patch
from app.agents.ensemble.schemas import ConsensusPlan


def _ok_result(decision="BUY", summary="Bull thesis."):
    return {"decision": decision, "full_report": summary, "short_summary": summary, "success": True, "error": None}


def _fail_result(error="timeout"):
    return {"decision": "ERROR", "full_report": "", "short_summary": "", "success": False, "error": error}


@pytest.mark.asyncio
async def test_run_ensemble_both_succeed():
    mock_plan = ConsensusPlan(
        ticker="NVDA", trade_date="2026-05-02",
        final_rating="BUY", confidence_score=0.75,
        model_agreement="Pro=BUY · Flash=OVERWEIGHT — leaning BUY",
        time_horizon="2-4 weeks", executive_summary="Strong."
    )
    with patch("app.agents.ensemble.service.analyze_stock", new_callable=AsyncMock,
               side_effect=[_ok_result("BUY"), _ok_result("OVERWEIGHT")]), \
         patch("app.agents.ensemble.service.synthesize", new_callable=AsyncMock, return_value=mock_plan):
        from app.agents.ensemble.service import run_ensemble
        plan = await run_ensemble("NVDA", "2026-05-02")
    assert plan.final_rating == "BUY"
    assert plan.confidence_score == 0.75


@pytest.mark.asyncio
async def test_run_ensemble_pro_fails_uses_flash():
    with patch("app.agents.ensemble.service.analyze_stock", new_callable=AsyncMock,
               side_effect=[_fail_result(), _ok_result("HOLD")]):
        from app.agents.ensemble.service import run_ensemble
        plan = await run_ensemble("AAPL", "2026-05-02")
    assert plan.final_rating == "HOLD"
    assert plan.confidence_score == 0.5
    assert "Flash" in plan.model_agreement


@pytest.mark.asyncio
async def test_run_ensemble_flash_fails_uses_pro():
    with patch("app.agents.ensemble.service.analyze_stock", new_callable=AsyncMock,
               side_effect=[_ok_result("SELL"), _fail_result()]):
        from app.agents.ensemble.service import run_ensemble
        plan = await run_ensemble("TSLA", "2026-05-02")
    assert plan.final_rating == "SELL"
    assert "Pro" in plan.model_agreement


@pytest.mark.asyncio
async def test_run_ensemble_both_fail_raises():
    with patch("app.agents.ensemble.service.analyze_stock", new_callable=AsyncMock,
               side_effect=[_fail_result("api down"), _fail_result("timeout")]):
        from app.agents.ensemble.service import run_ensemble
        with pytest.raises(RuntimeError, match="Both models failed"):
            await run_ensemble("MSFT", "2026-05-02")


@pytest.mark.asyncio
async def test_run_ensemble_passes_discovery_signals():
    mock_plan = ConsensusPlan(
        ticker="NVDA", trade_date="2026-05-02",
        final_rating="BUY", confidence_score=1.0,
        model_agreement="Both: BUY", time_horizon="2-4 weeks",
        executive_summary="Test.", discovery_signals=["volume_spike"]
    )
    with patch("app.agents.ensemble.service.analyze_stock", new_callable=AsyncMock,
               side_effect=[_ok_result(), _ok_result()]), \
         patch("app.agents.ensemble.service.synthesize", new_callable=AsyncMock, return_value=mock_plan):
        from app.agents.ensemble.service import run_ensemble
        plan = await run_ensemble("NVDA", "2026-05-02", discovery_signals=["volume_spike"])
    assert "volume_spike" in plan.discovery_signals
