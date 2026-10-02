"""Arabic text normalization.

Two levels are produced and the original is always preserved by callers:

* ``normalize_text`` - conservative, safe to store as ``normalized_text`` and to
  show to users: unifies digits, removes tatweel/control chars, normalizes
  whitespace and punctuation. Names are untouched apart from digit/tatweel cleanup.
* ``matching_key`` - aggressive, used only internally for comparisons/search:
  strips diacritics and unifies letter variants (أ/إ/آ -> ا, ى -> ي, ة -> ه, ...).
  Never stored as a replacement for what the caller said.
"""

from __future__ import annotations

import re
import unicodedata

ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
DIACRITICS_RE = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
TATWEEL = "ـ"
CONTROL_RE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
SPACE_RE = re.compile(r"\s+")
ARABIC_LETTER_RE = re.compile(r"[ء-يٱ-ۓۺ-ۿ]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

PUNCT_MAP = str.maketrans({"،": ",", "؛": ";", "؟": "?", "٪": "%", "٫": ".", "٬": ","})

LETTER_VARIANTS = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
        "ى": "ي", "ئ": "ي", "ؤ": "و",
        "ة": "ه",
        "گ": "ك", "ک": "ك", "ی": "ي", "ڤ": "ف", "پ": "ب", "چ": "ج",
    }
)


def to_western_digits(text: str) -> str:
    return text.translate(ARABIC_INDIC_DIGITS)


def normalize_text(text: str) -> str:
    """Conservative normalization suitable for storage next to the original."""
    t = unicodedata.normalize("NFC", text)
    t = CONTROL_RE.sub("", t)
    t = t.replace(TATWEEL, "")
    t = to_western_digits(t)
    t = t.translate(PUNCT_MAP)
    # Arabic decimal/thousand separators inside numbers: 6٫30 -> 6.30 handled above.
    t = SPACE_RE.sub(" ", t).strip()
    return t


def strip_diacritics(text: str) -> str:
    return DIACRITICS_RE.sub("", text)


def matching_key(text: str) -> str:
    """Aggressive folding for comparisons only (never stored as the transcript)."""
    t = normalize_text(text).lower()
    t = strip_diacritics(t)
    t = t.translate(LETTER_VARIANTS)
    t = re.sub(r"[^\w\s]", " ", t)
    return SPACE_RE.sub(" ", t).strip()


_DEFINITE = ("وال", "بال", "فال", "كال", "لل", "ال")


def strip_definite_article(token: str) -> str:
    for p in _DEFINITE:
        if token.startswith(p) and len(token) - len(p) >= 2:
            return token[len(p):]
    return token


def tokens(text: str) -> list[str]:
    return matching_key(text).split()


def script_ratio(text: str) -> tuple[float, float]:
    """Share of Arabic-script vs Latin-script *words* (word level handles code switching better)."""
    ar = en = 0
    for word in text.split():
        a, e = len(ARABIC_LETTER_RE.findall(word)), len(LATIN_LETTER_RE.findall(word))
        if a > e:
            ar += 1
        elif e > 0:
            en += 1
    total = ar + en
    if total == 0:
        return 0.0, 0.0
    return ar / total, en / total


_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-]{6,16}\d)(?!\d)")


def normalize_phone(text: str, default_country_code: str = "966") -> str | None:
    """Extract and normalize a phone number to E.164 (best effort)."""
    m = _PHONE_RE.search(to_western_digits(text))
    if not m:
        return None
    digits = re.sub(r"[^\d+]", "", m.group(1))
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0"):
        return f"+{default_country_code}{digits[1:]}"
    if digits.startswith(default_country_code):
        return "+" + digits
    return f"+{default_country_code}{digits}"


def similarity(a: str, b: str) -> float:
    """Token-overlap similarity on matching keys (0..1), robust to ال prefixes."""
    ta = {strip_definite_article(t) for t in tokens(a)}
    tb = {strip_definite_article(t) for t in tokens(b)}
    if not ta or not tb:
        return 0.0
    if ta <= tb or tb <= ta:
        return 1.0 if ta == tb else 0.85
    return len(ta & tb) / len(ta | tb)
