from datetime import date, datetime

import pytest

from app.parsing import clean_text, date_flag, parse_date, parse_datetime


@pytest.mark.parametrize("raw, expected", [
    ("22-10-2026", date(2026, 10, 22)),
    ("03-04-2026", date(2026, 4, 3)),          # day-first, never 4 March
    ("3/4/2026", date(2026, 4, 3)),
    ("03.04.26", date(2026, 4, 3)),
    ("2026-10-23T12:46:49.575Z", date(2026, 10, 23)),
    ("2026-10-23", date(2026, 10, 23)),
    (46317, date(2026, 10, 22)),               # Excel serial
    (46317.75, date(2026, 10, 22)),
    ("46317", date(2026, 10, 22)),
    ("22 Oct 2026", date(2026, 10, 22)),
    ("Oct 22, 2026", date(2026, 10, 22)),
    (datetime(2026, 10, 22, 9, 30), date(2026, 10, 22)),
    (date(2026, 10, 22), date(2026, 10, 22)),
    ("  ", None),
    (None, None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["13-13-2026", "31-02-2026", "next week", 12, True])
def test_parse_date_rejects(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_parse_datetime_keeps_time():
    assert parse_datetime("2026-10-23T12:46:49.575Z") == datetime(2026, 10, 23, 12, 46, 49)
    assert parse_datetime("30-10-2026") == datetime(2026, 10, 30)


def test_date_flag():
    today = date(2026, 10, 31)
    assert date_flag(date(2027, 10, 23), today) == "future"
    assert date_flag(date(2025, 10, 1), today) == "old"
    assert date_flag(date(2026, 10, 22), today) is None
    assert date_flag(None, today) is None


def test_clean_text():
    assert clean_text(854617.0) == "854617"
    assert clean_text("  DE-Java-Senior  ") == "DE-Java-Senior"
    assert clean_text("\nEPAM  Systems ") == "EPAM Systems"
    assert clean_text("007") == "007"
    assert clean_text("   ") is None
