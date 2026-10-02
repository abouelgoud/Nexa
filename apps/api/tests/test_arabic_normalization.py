import pytest

from nexa.nlp.arabic import matching_key, normalize_phone, normalize_text, similarity
from nexa.nlp.intents import classify_yes_no, is_human_request, keyword_intent
from nexa.nlp.language import SessionDialectTracker, detect_language


def test_arabic_indic_digits_are_normalized():
    assert normalize_text("الساعة ٧:٣٠ يوم ١٥") == "الساعة 7:30 يوم 15"
    assert normalize_text("رقمي ۰۵۵۱۲۳۴۵۶۷") == "رقمي 0551234567"


def test_tatweel_controls_and_spaces_removed_but_letters_kept():
    original = "مـــرحبا‏   بك يا أحمد"
    out = normalize_text(original)
    assert out == "مرحبا بك يا أحمد"
    # Names keep their hamza/letters in the stored normalized text
    assert "أحمد" in out


def test_original_text_never_modified():
    text = "أبغى أحجز موعد يوم الأحد"
    _ = normalize_text(text)
    _ = matching_key(text)
    assert text == "أبغى أحجز موعد يوم الأحد"


def test_matching_key_folds_spelling_variants():
    assert matching_key("أبغى") == matching_key("ابغي")
    assert matching_key("إستشارة") == matching_key("استشاره")
    assert matching_key("مُوْعِد") == matching_key("موعد")


def test_similarity_handles_definite_article():
    assert similarity("جلدية", "الجلدية") == 1.0
    assert similarity("موعد جلدية", "الجلدية") >= 0.85


@pytest.mark.parametrize("text,expected", [
    ("0551234567", "+966551234567"),
    ("رقمي ٠٥٥١٢٣٤٥٦٧", "+966551234567"),
    ("+971 50 123 4567", "+971501234567"),
    ("00966551234567", "+966551234567"),
    ("ما عندي رقم", None),
])
def test_phone_normalization(text, expected):
    assert normalize_phone(text) == expected


@pytest.mark.parametrize("text,dialect", [
    ("أبغى أحجز موعد", "sa"),
    ("عايز احجز معاد", "eg"),
    ("بدي احجز موعد هلق", "levant"),
    ("شكد سعر الكشف هواي غالي", "iq"),
    ("بغيت نحجز دابا", "ma"),
    ("اشتي موعد ذلحين", "ye"),
    ("أود حجز موعد من فضلك", "ar"),
])
def test_dialect_detection_is_probabilistic_metadata(text, dialect):
    info = detect_language(text)
    assert info.language == "ar"
    assert info.dialect == dialect
    assert 0 < info.dialect_confidence <= 1
    assert abs(sum(info.dialect_scores.values()) - 1) < 1e-6


def test_no_dialect_evidence_is_not_forced():
    info = detect_language("موعد")
    assert info.language == "ar" and info.dialect is None


@pytest.mark.parametrize("text,lang", [
    ("أبغى أحجز appointment.", "ar"),
    ("ممكن check لي الطلب؟", "ar"),
    ("أبغى الموعد next Monday", "ar"),
    ("I want to book an appointment please", "en"),
])
def test_code_switching_detection(text, lang):
    info = detect_language(text)
    assert info.language == lang
    if "appointment" in text and lang == "ar":
        assert info.code_switching


def test_dialect_tracker_accumulates_evidence():
    tracker = SessionDialectTracker()
    tracker.update(detect_language("عايز احجز"))
    tracker.update(detect_language("دلوقتي لو سمحت"))
    d, conf = tracker.best()
    assert d == "eg" and conf > 0.5
    assert SessionDialectTracker(tracker.to_state()).best()[0] == "eg"


@pytest.mark.parametrize("text,answer", [
    ("نعم", "yes"), ("ايوه", "yes"), ("أكيد احجز", "yes"), ("تمام", "yes"), ("yes please", "yes"),
    ("واخا", "yes"), ("لا", "no"), ("لا شكرا", "no"), ("no", "no"), ("لا لا", "no"), ("مدري", None),
])
def test_yes_no(text, answer):
    assert classify_yes_no(text) == answer


def test_human_request_detection():
    assert is_human_request("ابي اكلم موظف")
    assert is_human_request("I want to talk to a human")
    assert is_human_request("حولني على الاستقبال")
    assert not is_human_request("أبغى أحجز موعد")


def test_keyword_intent():
    intents = {"book": ["احجز", "موعد", "appointment"], "cancel": ["الغي", "cancel"]}
    assert keyword_intent("السلام عليكم، أبغى أحجز موعد جلدية.", intents) == "book"
    assert keyword_intent("I need to cancel", intents) == "cancel"
    assert keyword_intent("كم السعر", intents) is None
