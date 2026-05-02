"""Shared output schemas used across services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AnalysisPlan:
    """Single-model analysis result, used for Discord embeds and DB storage."""

    ticker: str
    trade_date: str
    final_rating: str
    executive_summary: str
    confidence_score: float = 0.5
    model_agreement: str = ""
    discovery_signals: List[str] = field(default_factory=list)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    price_target: Optional[float] = None
    time_horizon: str = ""
    key_catalysts: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list)
