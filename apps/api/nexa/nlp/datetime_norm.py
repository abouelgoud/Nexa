"""Date and time extraction for Arabic (multiple dialects), English and mixed speech.

Examples handled::

    "بكرة الساعة 7 مساء"        -> tomorrow 19:00
    "next Monday at 6:30 pm"   -> next Monday 18:30
    "الاثنين الجاي سبعة ونص"   -> next Monday 07:30 (ambiguous hour, see ``resolve_hour``)
    "أبغى الموعد next Monday"  -> next Monday
    "2026-10-05" / "5/10"      -> explicit dates (day/month order)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from nexa.nlp.arabic import matching_key, normalize_text

WEEKDAYS: dict[str, int] = {
    # Python weekday(): Monday=0 ... Sunday=6
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
    "الاثنين": 0, "الاتنين": 0, "اثنين": 0, "الثنين": 0, "الإثنين": 0, "اتنين": 0,
    "الثلاثاء": 1, "الثلاثا": 1, "الثلوث": 1, "ثلاثاء": 1, "التلات": 1, "التلاتاء": 1,
    "الاربعاء": 2, "الاربعا": 2, "الاربع": 2, "اربعاء": 2,
    "الخميس": 3, "خميس": 3,
    "الجمعه": 4, "جمعه": 4,
    "السبت": 5, "سبت": 5,
    "الاحد": 6, "احد": 6, "الحد": 6,
}

RELATIVE_DAYS: dict[str, int] = {
    "today": 0, "tonight": 0, "tomorrow": 1,
    "اليوم": 0, "الليله": 0,
    "بكره": 1, "بكرا": 1, "باكر": 1, "باجر": 1, "غدا": 1, "غدوه": 1, "الغد": 1, "بكري": 1, "غدوا": 1,
}
AFTER_TOMORROW = ("بعد بكره", "بعد بكرا", "بعد باكر", "بعد غد", "بعد الغد", "بعد باجر", "day after tomorrow")
NEXT_WORDS = ("الجاي", "القادم", "الجايه", "القادمه", "اللي جاي", "الي جاي", "next", "coming", "الياي")

NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
    "واحد": 1, "وحده": 1, "ثنتين": 2, "اثنين": 2, "اتنين": 2, "ثنين": 2, "ثلاث": 3, "ثلاثه": 3, "تلاته": 3,
    "تلات": 3, "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7,
    "ثمان": 8, "ثمانيه": 8, "تمانيه": 8, "ثمنيه": 8, "تمنيه": 8, "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
    "احدعش": 11, "حداش": 11, "احدي عشر": 11, "احد عشر": 11, "اطعش": 11,
    "اثنعش": 12, "اطنعش": 12, "اثنا عشر": 12, "اثني عشر": 12, "طنعش": 12,
}

PM_MARKERS = ("مساء", "مساءا", "مسا", "المسا", "المساء", "بالليل", "الليل", "العصر", "عصر", "المغرب", "مغرب",
              "العشا", "pm", "p.m", "evening", "night", "afternoon", "بعد الظهر", "الظهر", "ظهر")
AM_MARKERS = ("صباح", "صباحا", "الصبح", "الصباح", "صبح", "am", "a.m", "morning", "الفجر")


@dataclass
class DateTimeResult:
    date: date | None = None
    time: time | None = None
    ambiguous_meridiem: bool = False

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat() if self.date else None,
            "time": self.time.strftime("%H:%M") if self.time else None,
            "ambiguous_meridiem": self.ambiguous_meridiem,
        }


def _key(text: str) -> str:
    return " " + matching_key(text) + " "


def extract_date(text: str, today: date) -> date | None:
    t = normalize_text(text)
    # ISO date
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # d/m or d/m/yyyy (day-first as used across the Arab world)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        try:
            result = date(y, mo, d)
            if not m.group(3) and result < today:
                result = date(y + 1, mo, d)
            return result
        except ValueError:
            pass
    k = _key(text)
    for phrase in AFTER_TOMORROW:
        if f" {matching_key(phrase)} " in k:
            return today + timedelta(days=2)
    toks = k.split()
    for tok in toks:
        if tok in RELATIVE_DAYS:
            return today + timedelta(days=RELATIVE_DAYS[tok])
    is_next = any(f" {matching_key(w)} " in k for w in NEXT_WORDS)
    for tok in toks:
        for c in (tok, tok[1:] if tok.startswith(("و", "ب", "ل")) else tok):
            if c in WEEKDAYS:
                # "Monday" / "next Monday" / "الاثنين الجاي" all mean the coming Monday in conversation;
                # the same weekday as today means today unless "next" is said.
                delta = (WEEKDAYS[c] - today.weekday()) % 7
                if delta == 0 and is_next:
                    delta = 7
                return today + timedelta(days=delta)
    if "next week" in k or " الاسبوع الجاي " in k or " الاسبوع القادم " in k:
        return today + timedelta(days=7)
    return None


def extract_time(text: str) -> tuple[time | None, bool]:
    """Return (time, ambiguous_meridiem)."""
    t = normalize_text(text).lower()
    k = _key(text)
    hour: int | None = None
    minute = 0
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(?:الساعه|الساعة|ساعه|ساعة|at|@)\s*(\d{1,2})\b", t) or re.search(
            r"\b(\d{1,2})\s*(?:am|pm|a\.m|p\.m|ص|م|مساء|صباحا|الصبح|المسا|بالليل|العصر)", t
        )
        if m and int(m.group(1)) < 24:
            hour = int(m.group(1))
        else:
            for phrase, val in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
                pk = matching_key(phrase)
                if re.search(rf"(?:^| )(?:ال)?(?:ساعه )?{re.escape(pk)}(?: |$)", k.strip()):
                    if " ساعه " in k or " الساعه " in k or any(f" {matching_key(x)} " in k for x in PM_MARKERS + AM_MARKERS) or " ونص " in k or " وربع " in k or " الا ربع " in k:
                        hour = val
                        break
    if hour is None:
        return None, False
    if " ونص " in k or " و نص " in k or "half past" in t or " ونصف " in k:
        minute = 30
    elif " وربع " in k or "quarter past" in t:
        minute = 15
    elif " الا ربع " in k or "quarter to" in t:
        hour, minute = (hour - 1) % 24, 45
    elif " الا ثلث " in k:
        hour, minute = (hour - 1) % 24, 40
    elif " وثلث " in k:
        minute = 20
    is_pm = any(f" {matching_key(x)} " in k or re.search(rf"\d\s*{re.escape(x)}\b", t) for x in PM_MARKERS)
    is_pm = is_pm or bool(re.search(r"\d\s*م\b", t))
    is_am = any(f" {matching_key(x)} " in k or re.search(rf"\d\s*{re.escape(x)}\b", t) for x in AM_MARKERS)
    is_am = is_am or bool(re.search(r"\d\s*ص\b", t))
    ambiguous = False
    if hour <= 12:
        if is_pm and hour < 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
        elif not is_pm and not is_am and hour <= 12:
            ambiguous = True
    return time(hour % 24, minute), ambiguous


def extract_datetime(text: str, now: datetime) -> DateTimeResult:
    d = extract_date(text, now.date())
    tm, amb = extract_time(text)
    return DateTimeResult(date=d, time=tm, ambiguous_meridiem=amb)


def resolve_hour(tm: time, candidates: list[time]) -> time:
    """Resolve an ambiguous 12h time against available slots (prefer an exact match, then PM)."""
    if tm in candidates:
        return tm
    pm = time((tm.hour % 12) + 12, tm.minute)
    if pm in candidates:
        return pm
    return tm
