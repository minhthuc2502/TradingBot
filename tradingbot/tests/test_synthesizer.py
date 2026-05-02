from app.agents.ensemble.synthesizer import calculate_confidence, build_model_agreement_str


def test_confidence_identical_ratings():
    assert calculate_confidence("BUY", "BUY") == 1.0


def test_confidence_adjacent_ratings():
    assert calculate_confidence("BUY", "OVERWEIGHT") == 0.75
    assert calculate_confidence("SELL", "UNDERWEIGHT") == 0.75


def test_confidence_two_apart():
    assert calculate_confidence("BUY", "HOLD") == 0.50
    assert calculate_confidence("SELL", "HOLD") == 0.50


def test_confidence_opposite():
    assert calculate_confidence("BUY", "SELL") == 0.0


def test_confidence_unknown_rating_returns_0_5():
    assert calculate_confidence("UNKNOWN", "BUY") == 0.5


def test_model_agreement_both_same():
    assert build_model_agreement_str("BUY", "BUY", "BUY") == "Both: BUY"


def test_model_agreement_diverge():
    result = build_model_agreement_str("BUY", "HOLD", "BUY")
    assert "Pro=BUY" in result
    assert "Flash=HOLD" in result
    assert "leaning BUY" in result


def test_model_agreement_overweight():
    result = build_model_agreement_str("OVERWEIGHT", "OVERWEIGHT", "OVERWEIGHT")
    assert result == "Both: OVERWEIGHT"
