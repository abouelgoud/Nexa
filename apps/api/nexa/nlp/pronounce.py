"""Make written replies sound the way people speak them.

Arabic is written without short vowels, so a voice has to guess them, and the guess is classical Arabic: "أقدر"
(I can) comes out as "أُقَدِّر" (I appreciate), "أخدمك" as "أَخْدَمُك", "سارة" as "سَارَّة". ``speakable`` adds the vowels of
everyday spoken (Gulf / Saudi first) words so every voice says them like a person on the phone, plus any
pronunciations the business set for its own names and terms. Only the audio uses this text; transcripts keep
the original.
"""

from __future__ import annotations

import re

from nexa.nlp.arabic import DIACRITICS_RE, LETTER_VARIANTS

# Each word written as it is said; looked up without its vowels. Words whose spoken form depends on meaning
# ("تفضل": here you go / you prefer, "مرة": once / woman) are left to the voice.
SPOKEN = """
أَقْدَر تِقْدَر نِقْدَر يِقْدَر تِقْدِرِين تِقْدِرُون
أَبْغَى تِبْغَى نِبْغَى يِبْغَى تِبْغِين تِبْغُون يِبْغُون تِبِي تِبِين تِبُون
أَخْدِمَك نِخْدِمَك نِخْدِمْكُم أَخْدِمْكُم أَسَاعِدَك نِسَاعِدَك أَسَاعِدْكُم
أَحْجِز تِحْجِز نِحْجِز يِحْجِز أَحْجِزْلَك نِحْجِزْلَك حَجَزْت حَجَزْنَا حَجْزَك حَجْز
أَشُوف تِشُوف نِشُوف أَشُوفْلَك نِشُوفْلَك أَعْرِف تِعْرِف نِعْرِف
أَأَكِّد نِأَكِّد أَكِّد أَكَّدْت تَأْكِيد أَرْسِل نِرْسِل أَرْسَلْت
أَحْتَاج تِحْتَاج نِحْتَاج يِحْتَاج يِصِير مَا يِصِير
أَبْشِر أَبْشِرِي خَلِّنِي خَلِّينِي خَلَاص يِعْطِيك عَطْنِي أَعْطِيك
مَوْعِد مَوْعِدَك مَوَاعِيد الْمَوْعِد الْمَوَاعِيد عِنْدَك عِنْدِي عِنْدَنَا عِنْدِكُم
مَعَك مَعَاك مَعِي مَعَانَا عَشَان عَلَشَان
وِش إِيش شْلُون وِين مِتَى لِيش
الْحِين دِحِين بُكْرَة بَعْدِين اللِّي هَذَا هَذِي كِذَا هِنَا هِنَاك
فَضْلَك أَيّ تَمّ شِي ثَانِي زِين طَيِّب تَمَام أَكِيد يَعْنِي مُمْكِن لَازِم شْوَي لَحْظَة دَقِيقَة
حَيَّاك حَيَّاكُم هَلَا أَهْلًا مَرْحَبَا شُكْرًا الْعَفْو الْعَافْيَة السَّلَامَة
السَّلَام عَلَيْكُم وَعَلَيْكُم
الدُّكْتُور الدُّكْتُورَة دُكْتُور دُكْتُورَة طَبِيب الطَّبِيب طَبِيبَة الطَّبِيبَة مُعَيَّن
عِيَادَة الْعِيَادَة جِلْدِيَّة الْجِلْدِيَّة أَسْنَان الْأَسْنَان بَاطْنِيَّة الْبَاطْنِيَّة عُيُون الْعُيُون أَطْفَال الْأَطْفَال
الْمُسَاعِد الذَّكِي
وَاحِد اثْنِين ثَلَاث أَرْبَع خَمْس سِت سَبْع ثَمَان تِسْع عَشَر
رَقْم رَقْمَك جَوَّال جَوَّالَك اسْمَك اسْمِي
السَّاعَة الصُّبْح الظُّهُر الْعَصِر الْمَغْرِب الْعِشَا الْأُسْبُوع
السَّبْت الْأَحَد الْإِثْنِين الثُّلَاثَاء الْأَرْبِعَاء الْخَمِيس الْجُمْعَة
سَارَة نُورَة مُحَمَّد أَحْمَد فَاطِمَة خَالِد عَبْدَالله سَلْمَان رِيم لَيْلَى حَسَن مَرْيَم عَائِشَة يُوسُف
إِبْرَاهِيم فَهَد سُلْطَان عَبْدَالرَّحْمَن
"""

_WORD = re.compile(r"[ء-يً-ْٰٱ]+")
_PREFIXES = ("و", "ف")


def _key(word: str) -> str:
    return DIACRITICS_RE.sub("", word).translate(LETTER_VARIANTS)


_LEXICON: dict[str, str] = {_key(w): w for w in SPOKEN.split()}


def _spoken(word: str) -> str:
    if DIACRITICS_RE.search(word):  # already voweled (by the business or an earlier rule)
        return word
    found = _LEXICON.get(_key(word))
    if found:
        return found
    if len(word) > 3 and word[0] in _PREFIXES and (found := _LEXICON.get(_key(word[1:]))):
        return word[0] + "َ" + found
    return word


def parse_pronunciations(lines: list[str] | None) -> dict[str, str]:
    """``word = how to say it`` lines (as set on the agent) -> {word: spoken form}."""
    out: dict[str, str] = {}
    for line in lines or []:
        word, sep, say = line.partition("=")
        if sep and word.strip() and say.strip():
            out[word.strip()] = say.strip()
    return out


def speakable(text: str, custom: dict[str, str] | None = None) -> str:
    """The text a voice should read: the business's own pronunciations, then spoken Arabic vowels."""
    for word, say in sorted((custom or {}).items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", lambda _m, s=say: s, text, flags=re.IGNORECASE)
    return _WORD.sub(lambda m: _spoken(m.group(0)), text)
