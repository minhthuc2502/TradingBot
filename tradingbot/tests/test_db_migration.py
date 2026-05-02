from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from app.db.models import Base, AnalysisResult


def test_analysis_result_has_new_columns():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("analysis_results")}
    assert "confidence_score" in cols
    assert "model_agreement" in cols


def test_save_analysis_accepts_confidence_fields():
    from app.db.session import save_analysis
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        result = save_analysis(
            db,
            ticker="AAPL",
            analysis_date="2026-05-02",
            decision="BUY",
            short_summary="Test",
            full_report="Test report",
            success=True,
            error_message=None,
            confidence_score=0.75,
            model_agreement="Both: BUY",
        )
        db.commit()
        assert result.confidence_score == 0.75
        assert result.model_agreement == "Both: BUY"


def test_save_analysis_works_without_confidence_fields():
    """Existing callers without new params should still work."""
    from app.db.session import save_analysis
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        result = save_analysis(
            db,
            ticker="MSFT",
            analysis_date="2026-05-02",
            decision="HOLD",
            short_summary="Test",
            full_report="Report",
            success=True,
            error_message=None,
        )
        db.commit()
        assert result.confidence_score is None
        assert result.model_agreement is None


def test_migrate_db_adds_columns_to_existing_table():
    """Simulate a pre-migration database that lacks the new columns."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.db.session import migrate_db

    # Create table using old schema (without new columns)
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE analysis_results (
                id INTEGER PRIMARY KEY,
                ticker VARCHAR(20),
                analysis_date VARCHAR(10),
                decision VARCHAR(20),
                short_summary TEXT,
                full_report TEXT,
                success BOOLEAN,
                error_message TEXT,
                created_at DATETIME
            )
        """))
        conn.commit()

    # Verify columns are absent before migration
    inspector = inspect(engine)
    cols_before = {c["name"] for c in inspector.get_columns("analysis_results")}
    assert "confidence_score" not in cols_before
    assert "model_agreement" not in cols_before

    # Patch engine in session module temporarily
    import app.db.session as session_module
    original_engine = session_module.engine
    session_module.engine = engine
    try:
        migrate_db()
    finally:
        session_module.engine = original_engine

    # Verify columns exist after migration
    inspector2 = inspect(engine)
    cols_after = {c["name"] for c in inspector2.get_columns("analysis_results")}
    assert "confidence_score" in cols_after
    assert "model_agreement" in cols_after
