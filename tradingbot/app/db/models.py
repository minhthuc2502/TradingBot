from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Stock(Base):
    """Stocks on the watchlist."""

    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), unique=True, index=True, nullable=False)
    added_by = Column(String(50), nullable=True)  # WhatsApp number that added it
    created_at = Column(DateTime, server_default=func.now())


class AnalysisResult(Base):
    """Persisted output of a TradingAgents run."""

    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    analysis_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    decision = Column(String(20))                        # BUY / SELL / HOLD / ...
    short_summary = Column(Text)                         # 2-3 sentence excerpt
    full_report = Column(Text)                           # Complete agent output
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)       # 0.0–1.0 ensemble agreement
    model_agreement = Column(String(200), nullable=True)  # "Both: BUY" or "Pro=X · Flash=Y"
    created_at = Column(DateTime, server_default=func.now())


class BotConfig(Base):
    """Runtime key-value configuration (overridable via WhatsApp commands)."""

    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
