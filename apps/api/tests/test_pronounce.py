"""Replies are voiced the way people speak: everyday words get their spoken vowels, word endings are pausal."""

import sys
from pathlib import Path

import pytest

from nexa.nlp.pronounce import parse_pronunciations, speakable
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.speech_cache import fixed_phrases

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "tts"))
import spoken_ar  # noqa: E402


def test_spoken_vowels_for_everyday_words():
    # "أقدر" is "I can" (aqdar), not "I appreciate" (uqaddir).
    assert speakable("كيف أقدر أخدمك؟") == "كيف أَقْدَر أَخْدِمَك؟"
    assert speakable("تم حجز موعدك مع الدكتورة سارة.") == "تَمّ حَجْز مَوْعِدَك مع الدُّكْتُورَة سَارَة."
    assert speakable("اقدر") == "أَقْدَر"  # written without the hamza
    assert speakable("وأقدر") == "وَأَقْدَر"


def test_leaves_voweled_and_unknown_words_and_english():
    assert speakable("أُقَدِّر جهودك") == "أُقَدِّر جهودك"
    assert speakable("Your booking is confirmed.") == "Your booking is confirmed."


def test_business_pronunciations():
    custom = parse_pronunciations(["Nexa = نِكْسَا", "د. = دكتورة", "no separator", " = empty"])
    assert custom == {"Nexa": "نِكْسَا", "د.": "دكتورة"}
    assert speakable("Welcome to nexa, د. سارة", custom) == "Welcome to نِكْسَا, دُكْتُورَة سَارَة"
    assert speakable("Nexaland", custom) == "Nexaland"  # whole words only


def test_pre_rendered_lines_are_the_spoken_text():
    defn = AgentDefinition(name="A", languages=["ar"])
    defn.general.greeting = "كيف أقدر أخدمك؟"
    defn.voice.pronunciations = ["أخدمك = أَخْدِمْكُم"]
    assert "كيف أَقْدَر أَخْدِمْكُم؟" in fixed_phrases(defn, None, "ar")


@pytest.mark.parametrize(("voweled", "said"), [
    ("لَحْظَةٌ مِنْ فَضْلِكَ.", "لَحْظَ مِنْ فَضْلِكْ."),  # no case endings; ta marbuta is "-a"
    ("شُكْرًا", "شُكْرًا"),
    ("الذَّكِيِّ", "الذَّكِيّْ"),
    ("مِتَى", "مِتَى"),
])
def test_piper_pausal_endings(voweled, said):
    assert spoken_ar._WORD.sub(lambda m: spoken_ar._pausal(m.group(0)), voweled) == said
