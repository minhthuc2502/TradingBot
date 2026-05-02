import pytest
from app.services.scheduler import _parse_hhmm


def test_parse_hhmm_valid_midnight():
    assert _parse_hhmm("00:00") == (0, 0)


def test_parse_hhmm_valid_evening():
    assert _parse_hhmm("23:00") == (23, 0)


def test_parse_hhmm_valid_midday():
    assert _parse_hhmm("12:30") == (12, 30)


def test_parse_hhmm_invalid_raises():
    with pytest.raises(ValueError, match="Invalid time format"):
        _parse_hhmm("invalid")


def test_parse_hhmm_missing_colon_raises():
    with pytest.raises(ValueError):
        _parse_hhmm("1200")
