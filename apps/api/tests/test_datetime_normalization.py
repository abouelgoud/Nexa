from datetime import date, datetime, time

import pytest

from nexa.nlp.datetime_norm import extract_date, extract_datetime, extract_time, resolve_hour

NOW = datetime(2026, 10, 2, 10, 0)  # Friday
TODAY = NOW.date()


@pytest.mark.parametrize("text,expected", [
    ("اليوم", date(2026, 10, 2)),
    ("بكرة", date(2026, 10, 3)),
    ("باجر", date(2026, 10, 3)),
    ("tomorrow", date(2026, 10, 3)),
    ("بعد بكرة", date(2026, 10, 4)),
    ("الاثنين", date(2026, 10, 5)),
    ("يوم الإثنين", date(2026, 10, 5)),
    ("أبغى الموعد next Monday", date(2026, 10, 5)),
    ("الأحد الجاي", date(2026, 10, 4)),
    ("الجمعة الجاية", date(2026, 10, 9)),
    ("الجمعة", date(2026, 10, 2)),
    ("2026-11-20", date(2026, 11, 20)),
    ("١٥/١٠", date(2026, 10, 15)),
    ("1/9", date(2027, 9, 1)),
])
def test_dates(text, expected):
    assert extract_date(text, TODAY) == expected


@pytest.mark.parametrize("text,expected,ambiguous", [
    ("الساعة 7 مساءً", time(19, 0), False),
    ("6:30 pm", time(18, 30), False),
    ("٦:٣٠ م", time(18, 30), False),
    ("سبعة ونص بالليل", time(19, 30), False),
    ("الساعة عشرة الصبح", time(10, 0), False),
    ("الساعة ثمان الا ربع", time(7, 45), True),
    ("at 3", time(3, 0), True),
    ("الساعة 15:00", time(15, 0), False),
])
def test_times(text, expected, ambiguous):
    t, amb = extract_time(text)
    assert t == expected
    assert amb is ambiguous


def test_no_time_in_plain_text():
    assert extract_time("أبغى أحجز موعد")[0] is None


def test_combined_mixed_language():
    r = extract_datetime("بكرة at 6:30 pm", NOW)
    assert r.date == date(2026, 10, 3) and r.time == time(18, 30)


def test_ambiguous_hour_resolved_against_slots():
    assert resolve_hour(time(7, 0), [time(19, 0), time(18, 30)]) == time(19, 0)
    assert resolve_hour(time(9, 0), [time(9, 0), time(21, 0)]) == time(9, 0)
