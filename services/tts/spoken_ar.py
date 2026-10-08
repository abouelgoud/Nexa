"""Arabic for the Piper voice the way people say it, not read out like classical Arabic.

Piper vowels Arabic text with a small model (libtashkeel) trained on classical text, which adds case endings to
every word ("لَحْظَةٌ مِنْ فَضْلِكَ" -> lahzatun min fadlika). People pause on word endings: "لحظة من فضلك" is
"lahza min fadlak". Vowels already in the text (the API adds them for everyday spoken words) are kept as hints.
"""

from __future__ import annotations

import re
import threading

SHADDA, SUKUN = "ّ", "ْ"
_WORD = re.compile(r"[ء-يً-ْٰ]+")
_MARKS = re.compile(r"[ً-ْٰ]+$")
_LONG = "اىوي"

_diacritizer = None
_lock = threading.Lock()


def _pausal(word: str) -> str:
    if word.endswith(("ًا", "اً", "ًى")):  # "شكرًا", "أهلًا" keep their -an
        return word
    marks = _MARKS.search(word)
    base = word[: marks.start()] if marks else word
    shadda = SHADDA if marks and SHADDA in marks.group(0) else ""
    if not base:
        return word
    if base[-1] == "ة":  # "لحظة" -> lahza
        return base[:-1]
    if base[-1] in _LONG and not shadda:
        return base
    return base + shadda + SUKUN


def spoken(text: str) -> str:
    """Fully vowel the text (keeping given vowels) with pausal word endings."""
    global _diacritizer
    with _lock:
        if _diacritizer is None:
            from piper.tashkeel import TashkeelDiacritizer

            _diacritizer = TashkeelDiacritizer()
        voweled = _diacritizer(text)
    return _WORD.sub(lambda m: _pausal(m.group(0)), voweled)
