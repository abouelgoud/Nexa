"""Deterministic lexicons for safety-critical decisions.

Confirmation (yes/no) and explicit human-handoff requests are business rules and
must not depend on the LLM. These lexicons cover MSA, Gulf, Egyptian, Levantine,
Iraqi and Maghrebi variants plus English.
"""

from __future__ import annotations

from nexa.nlp.arabic import matching_key

YES = [
    "نعم", "اي", "ايه", "ايوه", "ايوا", "اه", "أجل", "اجل", "بلى", "تمام", "طيب", "اوكي", "اوك", "ماشي", "موافق",
    "اكيد", "أكيد", "صح", "صحيح", "زين", "ابشر", "يب", "يس", "اكد", "أكد", "احجز", "احجزه", "احجزي", "احجزلي",
    "خلاص", "هيه", "اييه", "واخا", "باهي", "مزيان", "اكيد طبعا", "طبعا", "بالضبط", "يلا", "تم",
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "correct", "confirm", "confirmed", "please do", "go ahead",
    "right", "exactly", "of course", "absolutely",
]
NO = [
    "لا", "لأ", "لاء", "لا شكرا", "مو", "مش", "ما ابي", "ما ابغى", "ما ابغي", "مابي", "مابغى", "مابغي", "ابد", "أبدا",
    "ابدا", "كلا", "الغ", "ألغ", "الغي", "ألغي", "بلاش", "خليها", "غير", "غيره", "مب", "لالا", "لا لا", "ماشي لا",
    "no", "nope", "nah", "cancel", "don't", "do not", "not now", "wrong", "change", "stop",
]
HUMAN_REQUEST = [
    "موظف", "موظفه", "انسان", "إنسان", "شخص", "احد", "حد", "بشري", "خدمه العملاء", "خدمة العملاء", "الاستقبال",
    "الريسبشن", "مدير", "المدير", "اكلم", "أكلم", "كلمني", "حولني", "حوليني", "تحويل", "عايز اكلم", "بدي احكي",
    "human", "agent", "representative", "operator", "real person", "someone", "receptionist", "manager", "transfer",
]
HUMAN_REQUEST_PHRASES = [
    "ابي اكلم", "ابغى اكلم", "ابغي اكلم", "ابي موظف", "ابغى موظف", "ابغي موظف", "عايز اكلم", "عاوز اكلم", "بدي احكي",
    "اريد اكلم", "اريد موظف", "حولني", "حوليني", "كلمني موظف", "ابي احد", "ابغى احد", "اكلم احد", "اكلم شخص",
    "talk to a human", "speak to a human", "talk to someone", "speak to someone", "real person", "talk to an agent",
    "speak to an agent", "representative", "operator", "transfer me", "customer service", "خدمه العملاء",
    "الاستقبال", "اكلم الاستقبال", "اكلم الريسبشن",
]


def _contains(k: str, phrase: str) -> bool:
    p = matching_key(phrase)
    return f" {p} " in f" {k} "


def classify_yes_no(text: str) -> str | None:
    """Return 'yes', 'no' or None (unclear). Negation wins when both are present."""
    k = matching_key(text)
    if not k:
        return None
    no_hit = any(_contains(k, w) for w in NO)
    yes_hit = any(_contains(k, w) for w in YES)
    # "لا، تمام" is ambiguous; "نعم لا" too - treat as unclear.
    if no_hit and yes_hit:
        first = k.split()[0]
        if any(matching_key(w) == first for w in NO):
            return "no"
        return None
    if no_hit:
        return "no"
    if yes_hit:
        return "yes"
    return None


def is_human_request(text: str) -> bool:
    k = matching_key(text)
    return any(_contains(k, p) for p in HUMAN_REQUEST_PHRASES)


def keyword_intent(text: str, intents: dict[str, list[str]]) -> str | None:
    """Match configured keywords (any language) to an intent; best score wins."""
    k = matching_key(text)
    best, best_score = None, 0
    for intent, words in intents.items():
        score = sum(1 for w in words if w and (_contains(k, w) or (len(matching_key(w)) >= 4 and matching_key(w) in k)))
        if score > best_score:
            best, best_score = intent, score
    return best
