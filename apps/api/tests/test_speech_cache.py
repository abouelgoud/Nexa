"""Natural voices: phrase splitting and pre-rendering of an agent's fixed lines."""

from nexa.providers import registry
from nexa.providers.tts.base import SynthesisResult, TTSProvider
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.speech_cache import fixed_phrases, speech_chunks, warm_agent_voice


def test_speech_chunks_split_at_punctuation_and_keep_phrases_short():
    assert speech_chunks("أكيد. أي تخصص تحتاج؟") == ["أكيد. أي تخصص تحتاج؟"]  # a one-word piece joins the next
    assert speech_chunks("One moment, please.") == ["One moment, please."]
    assert speech_chunks("تمام، تم حجز موعدك. هل تحتاج أي شي ثاني؟") == ["تمام، تم حجز موعدك.", "هل تحتاج أي شي ثاني؟"]
    long = "عندي موعد يوم الأحد الساعة أربعة ونص مع الدكتورة سارة العتيبي في قسم الجلدية بالدور الثاني"
    parts = speech_chunks(long)
    assert " ".join(parts) == long and all(len(p.split()) <= 8 for p in parts)
    assert parts[0] == "عندي موعد يوم الأحد"  # short first phrase: the caller hears something sooner
    assert speech_chunks("  ") == []


def test_fixed_phrases_skip_lines_with_variables():
    defn = AgentDefinition(name="Clinic", languages=["ar", "en"])
    defn.general.greeting = "أهلاً بك في {{business_name}}. كيف أقدر أساعدك؟"
    defn.general.business_name = "عيادة الشفاء"
    graph = {"nodes": [
        {"config": {"prompt": "هل تفضل طبيب معين؟", "prompt_en": "Do you prefer a specific doctor?"}},
        {"config": {"prompt": "عندي {{slots.records|list:label}}. أي واحد يناسبك؟"}},
        {"config": {"text": "تم حجز موعدك.", "text_en": "Your appointment is booked."}},
    ]}
    ar = fixed_phrases(defn, graph, "ar")
    assert "أهلاً بك في عيادة الشفاء." in ar and "كيف أقدر أساعدك؟" in ar and "لحظة من فضلك." in ar
    assert "هل تفضل طبيب معين؟" in ar and "تم حجز موعدك." in ar
    assert not any("{{" in p or "عندي" in p for p in ar)
    en = fixed_phrases(defn, graph, "en")
    assert "Do you prefer a specific doctor?" in en and "Your appointment is booked." in en
    assert not any("طبيب" in p for p in en)


class RecordingNeural(TTSProvider):
    name = "neural"

    def __init__(self):
        self.phrases = []

    async def synthesize(self, text, *, voice_id, language, speed=1.0):
        self.phrases.append((language, voice_id, text))
        return SynthesisResult(audio=b"RIFF", sample_rate=24000)

    async def health(self):
        return True


async def test_saving_an_agent_with_a_natural_voice_pre_renders_its_fixed_lines(account):
    neural = RecordingNeural()
    registry.override("tts:neural", neural)
    agent = (await account.post("/agents", json={"name": "Clinic", "template_key": "doctor_appointment",
                                                  "business_name": "عيادة الشفاء"})).json()
    cfg = {**agent["draft_config"], "voice": {**agent["draft_config"]["voice"], "provider": "neural",
                                               "voice_id": "noura"}}
    from uuid import UUID

    await account.put(f"/agents/{agent['id']}/config", json=cfg)
    count = await warm_agent_voice(UUID(account.tenant_id), UUID(agent["id"]))
    assert count > 0
    texts = {t for _, _, t in neural.phrases}
    assert "لحظة من فضلك." in texts and all(v == "noura" for _, v, _ in neural.phrases)
    assert all(len(t.split()) <= 8 for t in texts)  # same phrases live calls request
