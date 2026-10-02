"""Language and Arabic dialect detection.

Dialect detection is *probabilistic metadata*: it never blocks the conversation
and callers are never asked to choose a dialect. The lexicon-based detector is
the default implementation of ``DialectDetector`` and can be replaced by a
model later without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from nexa.nlp.arabic import script_ratio, strip_definite_article, tokens

# Marker words (in matching-key form) and the dialects they indicate with weights.
DIALECT_MARKERS: dict[str, dict[str, float]] = {
    # Gulf / Saudi
    "ابغي": {"sa": 1.0, "gulf": 0.9, "kw": 0.6, "ae": 0.6, "qa": 0.6, "bh": 0.6},
    "ابغا": {"sa": 1.0, "gulf": 0.8},
    "ابي": {"sa": 0.8, "gulf": 0.8, "kw": 0.7, "ae": 0.6},
    "ودي": {"sa": 0.8, "gulf": 0.6},
    "وش": {"sa": 1.0, "gulf": 0.5},
    "ايش": {"sa": 0.8, "gulf": 0.5, "levant": 0.3, "ye": 0.4},
    "زين": {"gulf": 0.6, "sa": 0.6, "iq": 0.5},
    "حيل": {"gulf": 0.7, "kw": 0.7},
    "يبه": {"gulf": 0.5},
    "الحين": {"sa": 0.8, "gulf": 0.8, "kw": 0.6},
    "دحين": {"sa": 0.9},
    "كذا": {"sa": 0.6, "gulf": 0.5},
    "ابشر": {"sa": 0.8, "gulf": 0.6},
    "مره": {"sa": 0.6},
    "شلونك": {"gulf": 0.8, "kw": 0.9, "iq": 0.7},
    "شلون": {"gulf": 0.6, "kw": 0.8, "iq": 0.8},
    "باجر": {"kw": 0.9, "iq": 0.7, "gulf": 0.5},
    "عساك": {"gulf": 0.6, "kw": 0.6},
    "علومك": {"sa": 0.7, "gulf": 0.6},
    # Iraqi
    "اريد": {"iq": 0.9, "ar": 0.3},
    "هواي": {"iq": 1.0},
    "اكو": {"iq": 1.0, "kw": 0.6},
    "ماكو": {"iq": 1.0, "kw": 0.6},
    "شكد": {"iq": 1.0},
    "اغاتي": {"iq": 0.9},
    # Egyptian
    "عايز": {"eg": 1.0, "sd": 0.4},
    "عاوز": {"eg": 1.0},
    "عايزه": {"eg": 1.0},
    "ازيك": {"eg": 0.9},
    "دلوقتي": {"eg": 1.0},
    "ازاي": {"eg": 1.0},
    "امتي": {"eg": 0.7},
    "فين": {"eg": 0.8, "sd": 0.4},
    "كده": {"eg": 0.9},
    "اوي": {"eg": 0.9},
    "بتاع": {"eg": 0.8},
    "مش": {"eg": 0.6, "levant": 0.5, "ly": 0.4, "tn": 0.3},
    "حضرتك": {"eg": 0.7},
    # Levantine
    "بدي": {"levant": 1.0},
    "بدك": {"levant": 1.0},
    "هلق": {"levant": 1.0},
    "هلا": {"levant": 0.4, "gulf": 0.4},
    "كتير": {"levant": 0.8, "eg": 0.4},
    "شو": {"levant": 0.9, "gulf": 0.3},
    "منيح": {"levant": 1.0},
    "هيك": {"levant": 0.9},
    "ليش": {"levant": 0.5, "gulf": 0.5, "sa": 0.4, "iq": 0.4},
    # Sudanese
    "داير": {"sd": 0.9, "ly": 0.4},
    "دايره": {"sd": 0.9},
    "زول": {"sd": 1.0},
    "ياخ": {"sd": 0.6},
    # Yemeni
    "اشتي": {"ye": 1.0},
    "ذلحين": {"ye": 1.0},
    "قده": {"ye": 0.5},
    # Libyan
    "نبي": {"ly": 0.9, "tn": 0.4},
    "توا": {"ly": 0.9, "tn": 0.6},
    "باهي": {"ly": 0.9, "tn": 0.8},
    # Tunisian
    "نحب": {"tn": 0.9, "dz": 0.6, "ma": 0.3},
    "برشا": {"tn": 1.0},
    "شنوه": {"tn": 0.9},
    "ياسر": {"tn": 0.8, "dz": 0.5},
    # Algerian
    "واش": {"dz": 0.9, "ma": 0.6},
    "بزاف": {"dz": 0.8, "ma": 0.8},
    "راني": {"dz": 0.9},
    "حاب": {"dz": 0.6, "tn": 0.4},
    # Moroccan
    "بغيت": {"ma": 1.0, "dz": 0.5},
    "دابا": {"ma": 1.0},
    "شنو": {"ma": 0.6, "iq": 0.5, "gulf": 0.4},
    "واخا": {"ma": 1.0},
    "مزيان": {"ma": 0.9, "dz": 0.5},
    "ديال": {"ma": 1.0},
    # Modern Standard Arabic
    "اود": {"ar": 1.0},
    "ارغب": {"ar": 1.0},
    "سوف": {"ar": 0.8},
    "لماذا": {"ar": 0.9},
    "ماذا": {"ar": 0.8},
    "الان": {"ar": 0.6},
}

_REGIONAL = {"ae": "gulf", "kw": "gulf", "qa": "gulf", "bh": "gulf", "om": "gulf"}


@dataclass
class LanguageInfo:
    language: str  # ar | en | unknown
    code_switching: bool
    arabic_ratio: float
    dialect: str | None = None
    dialect_confidence: float = 0.0
    dialect_scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "code_switching": self.code_switching,
            "arabic_ratio": round(self.arabic_ratio, 3),
            "dialect": self.dialect,
            "dialect_confidence": round(self.dialect_confidence, 3),
            "dialect_scores": {k: round(v, 3) for k, v in self.dialect_scores.items()},
        }


class DialectDetector(Protocol):
    def detect(self, text: str, allowed: list[str] | None = None) -> tuple[str | None, float, dict[str, float]]: ...


class LexiconDialectDetector:
    def detect(self, text: str, allowed: list[str] | None = None) -> tuple[str | None, float, dict[str, float]]:
        scores: dict[str, float] = {}
        for tok in tokens(text):
            for cand in {tok, strip_definite_article(tok), tok[1:] if tok.startswith("و") and len(tok) > 3 else tok}:
                for dialect, w in DIALECT_MARKERS.get(cand, {}).items():
                    scores[dialect] = scores.get(dialect, 0.0) + w
        if allowed:
            allowed_set = set(allowed)
            scores = {d: s for d, s in scores.items() if d in allowed_set or _REGIONAL.get(d) in allowed_set}
        total = sum(scores.values())
        if total <= 0:
            return None, 0.0, {}
        probs = {d: s / total for d, s in sorted(scores.items(), key=lambda kv: -kv[1])}
        best, p = next(iter(probs.items()))
        # Confidence grows with evidence mass but is capped by the share of the best guess.
        confidence = p * min(1.0, total / 2.0)
        return best, confidence, probs


_default_detector: DialectDetector = LexiconDialectDetector()


def detect_language(
    text: str, allowed_dialects: list[str] | None = None, detector: DialectDetector | None = None
) -> LanguageInfo:
    ar, en = script_ratio(text)
    if ar == 0 and en == 0:
        return LanguageInfo(language="unknown", code_switching=False, arabic_ratio=0.0)
    language = "ar" if ar >= en else "en"
    code_switching = ar > 0.05 and en > 0.05
    info = LanguageInfo(language=language, code_switching=code_switching, arabic_ratio=ar)
    if ar > 0:
        d, conf, scores = (detector or _default_detector).detect(text, allowed_dialects)
        info.dialect, info.dialect_confidence, info.dialect_scores = d, conf, scores
    return info


class SessionDialectTracker:
    """Accumulates dialect evidence across turns (exponential decay)."""

    def __init__(self, state: dict | None = None, decay: float = 0.8):
        self.scores: dict[str, float] = dict((state or {}).get("scores", {}))
        self.decay = decay

    def update(self, info: LanguageInfo) -> tuple[str | None, float]:
        for k in list(self.scores):
            self.scores[k] *= self.decay
        for d, p in info.dialect_scores.items():
            self.scores[d] = self.scores.get(d, 0.0) + p * max(info.dialect_confidence, 0.2)
        return self.best()

    def best(self) -> tuple[str | None, float]:
        total = sum(self.scores.values())
        if total <= 0:
            return None, 0.0
        d, s = max(self.scores.items(), key=lambda kv: kv[1])
        return d, s / total

    def to_state(self) -> dict:
        return {"scores": {k: round(v, 4) for k, v in self.scores.items() if v > 0.001}}
