from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


class EnsembleState(TypedDict):
    ticker: str
    trade_date: str
    pro_result: dict
    flash_result: dict
    pro_rating: str
    flash_rating: str


class ConsensusPlan(BaseModel):
    ticker: str
    trade_date: str
    final_rating: str              # BUY | OVERWEIGHT | HOLD | UNDERWEIGHT | SELL
    confidence_score: float        # 0.0–1.0
    model_agreement: str = ""
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    price_target: Optional[float] = None
    time_horizon: str = "2-4 weeks"
    executive_summary: str = ""
    key_catalysts: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    discovery_signals: List[str] = Field(default_factory=list)
