"""Database session management and all CRUD helpers.

Keeps data-access logic in one place so services stay thin.
All public functions accept an explicit ``Session`` so callers control
transaction boundaries with ``get_db()``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, func as sql_func, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import AnalysisResult, Base, BotConfig, Stock

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite only
    echo=settings.debug,
)

_SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a transactional DB session; commit on success, rollback on error."""
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables and seed initial data."""
    Base.metadata.create_all(bind=engine)
    migrate_db()
    with get_db() as db:
        _seed_defaults(db)


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def migrate_db() -> None:
    """Add columns introduced after initial schema creation. Safe to re-run."""
    from sqlalchemy.exc import OperationalError

    new_columns = [
        "ALTER TABLE analysis_results ADD COLUMN confidence_score REAL",
        "ALTER TABLE analysis_results ADD COLUMN model_agreement TEXT",
    ]
    with engine.connect() as conn:
        for stmt in new_columns:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except OperationalError:
                pass  # column already exists


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


def get_watchlist(db: Session) -> list[Stock]:
    return db.query(Stock).order_by(Stock.ticker).all()


def add_stock(db: Session, ticker: str, added_by: str | None = None) -> Stock:
    stock = Stock(ticker=ticker.upper(), added_by=added_by)
    db.add(stock)
    db.flush()
    return stock


def remove_stock(db: Session, ticker: str) -> bool:
    stock = db.query(Stock).filter(Stock.ticker == ticker.upper()).first()
    if stock:
        db.delete(stock)
        db.flush()
        return True
    return False


def stock_exists(db: Session, ticker: str) -> bool:
    return (
        db.query(Stock).filter(Stock.ticker == ticker.upper()).first() is not None
    )


# ---------------------------------------------------------------------------
# Analysis results CRUD
# ---------------------------------------------------------------------------


def save_analysis(
    db: Session,
    *,
    ticker: str,
    analysis_date: str,
    decision: str,
    short_summary: str | None,
    full_report: str | None,
    success: bool,
    error_message: str | None,
    confidence_score: float | None = None,
    model_agreement: str | None = None,
) -> AnalysisResult:
    result = AnalysisResult(
        ticker=ticker.upper(),
        analysis_date=analysis_date,
        decision=decision,
        short_summary=short_summary,
        full_report=full_report,
        success=success,
        error_message=error_message,
        confidence_score=confidence_score,
        model_agreement=model_agreement,
    )
    db.add(result)
    db.flush()
    return result


def get_latest_analyses(
    db: Session, tickers: list[str] | None = None
) -> list[AnalysisResult]:
    """Return the most-recent successful analysis per ticker."""
    q = db.query(AnalysisResult).filter(AnalysisResult.success.is_(True))
    if tickers:
        q = q.filter(AnalysisResult.ticker.in_([t.upper() for t in tickers]))

    # Sub-query: latest created_at per ticker
    subq = (
        db.query(
            AnalysisResult.ticker,
            sql_func.max(AnalysisResult.created_at).label("max_ts"),
        )
        .group_by(AnalysisResult.ticker)
        .subquery()
    )
    return (
        q.join(
            subq,
            (AnalysisResult.ticker == subq.c.ticker)
            & (AnalysisResult.created_at == subq.c.max_ts),
        )
        .order_by(AnalysisResult.ticker)
        .all()
    )


# ---------------------------------------------------------------------------
# Bot config CRUD
# ---------------------------------------------------------------------------


def get_config(db: Session, key: str, default: str = "") -> str:
    row = db.query(BotConfig).filter(BotConfig.key == key).first()
    return row.value if row else default


def set_config(db: Session, key: str, value: str) -> None:
    row = db.query(BotConfig).filter(BotConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(BotConfig(key=key, value=value))
    db.flush()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_defaults(db: Session) -> None:
    """Populate config & watchlist on first run."""
    for key, value in [
        ("analysis_time", settings.analysis_time),
        ("analysis_timezone", settings.analysis_timezone),
    ]:
        if not db.query(BotConfig).filter(BotConfig.key == key).first():
            db.add(BotConfig(key=key, value=value))

    existing_tickers = {s.ticker for s in db.query(Stock).all()}
    for ticker in settings.default_watchlist_list:
        if ticker not in existing_tickers:
            db.add(Stock(ticker=ticker, added_by="system"))

    db.flush()
