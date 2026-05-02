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
