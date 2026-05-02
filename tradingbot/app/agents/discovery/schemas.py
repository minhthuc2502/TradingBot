from __future__ import annotations

from typing import List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


class CandidateScore(BaseModel):
    ticker: str
    confluence_score: float = 0.0
    signals: List[str] = Field(default_factory=list)
    priority: str = "LOW"  # HIGH | MEDIUM | LOW


class DiscoveryResult(BaseModel):
    candidates: List[CandidateScore]
    top_tickers: List[str]


class DiscoveryState(TypedDict):
    universe: List[str]
    discovery_date: str
    volume_candidates: List[dict]
    news_candidates: List[dict]
    technical_candidates: List[dict]
    discovery_result: Optional[dict]
    selected_tickers: List[str]
