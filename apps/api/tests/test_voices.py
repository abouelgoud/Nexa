"""Natural voices (ElevenLabs, Azure dialect voices, self-hosted neural with cloning) and recognition accuracy aids."""

import io
import json
import wave

import httpx
import pytest

from nexa.providers import registry
from nexa.providers.audio import is_wav, pcm16_to_wav, to_wav_mono
from nexa.providers.stt.azure import AzureSTT
from nexa.providers.stt.base import STTProvider, TranscriptionResult
from nexa.providers.stt.elevenlabs import ElevenLabsSTT
from nexa.providers.stt.whisper_http import WhisperHTTPSTT
from nexa.providers.tts.azure import AzureTTS, build_ssml, voice_for_dialect
from nexa.providers.tts.base import SynthesisResult, TTSProvider
from nexa.providers.tts.elevenlabs import ElevenLabsTTS
from nexa.providers.tts.neural_http import NeuralHTTPTTS
from nexa.schemas.agent_definition import AgentDefinition
from nexa.services.voices import resolve_voice, stt_keywords


def tone_wav(rate=48000, seconds=0.5, channels=1) -> bytes:
    import array
    import math

    n = int(rate * seconds)
    s = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n) for _ in range(channels)))
    return pcm16_to_wav(s.tobytes(), rate, channels)


def test_resampling_to_16k_mono():
    out = to_wav_mono(tone_wav(48000, 0.5, 2), 16000)
    with wave.open(io.BytesIO(out)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (16000, 1, 8000)
    assert is_wav(out) and not is_wav(b"\x1aE\xdf\xa3webm")


async def test_elevenlabs_tts_request():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(path=req.url.path, params=dict(req.url.params), key=req.headers["xi-api-key"], body=json.loads(req.content))
        return httpx.Response(200, content=b"\x00\x01" * 2205)

    tts = ElevenLabsTTS("k-123", "eleven_flash_v2_5", transport=httpx.MockTransport(handler))
    r = await tts.synthesize("أهلاً", voice_id="VOICE1", language="ar", speed=1.1)
    assert seen["path"] == "/v1/text-to-speech/VOICE1" and seen["params"] == {"output_format": "pcm_22050"}
    assert seen["key"] == "k-123" and seen["body"]["language_code"] == "ar"
    assert seen["body"]["voice_settings"]["speed"] == 1.1
    assert is_wav(r.audio) and r.sample_rate == 22050


async def test_azure_tts_ssml_and_dialect_voices():
    assert voice_for_dialect("eg", "female") == "ar-EG-SalmaNeural"
    assert voice_for_dialect("sa", "male") == "ar-SA-HamedNeural"
    ssml = build_ssml("أهلاً <وسهلاً> & مرحبا", "ar-KW-FahedNeural", 1.1)
    assert "xml:lang='ar-KW'" in ssml and "name='ar-KW-FahedNeural'" in ssml and "rate='+10%'" in ssml
    assert "&lt;وسهلاً&gt; &amp;" in ssml
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), fmt=req.headers["X-Microsoft-OutputFormat"], key=req.headers["Ocp-Apim-Subscription-Key"])
        return httpx.Response(200, content=tone_wav(24000))

    r = await AzureTTS("az", "uaenorth", transport=httpx.MockTransport(handler)).synthesize(
        "مرحبا", voice_id="ar-SA-HamedNeural", language="ar")
    assert seen["url"] == "https://uaenorth.tts.speech.microsoft.com/cognitiveservices/v1"
    assert seen["fmt"] == "riff-24khz-16bit-mono-pcm" and seen["key"] == "az" and is_wav(r.audio)


async def test_elevenlabs_scribe_with_keyterms():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = req.content.decode("utf-8", "ignore")
        return httpx.Response(200, json={"text": "أبغى موعد مع د. سارة العتيبي", "language_code": "ara",
                                         "language_probability": 0.98,
                                         "words": [{"text": "أبغى", "type": "word", "start": 0, "end": 1.4}]})

    r = await ElevenLabsSTT("k", transport=httpx.MockTransport(handler)).transcribe(
        b"RIFF....", keywords=["سارة العتيبي", "الجلدية"])
    assert r.text.endswith("سارة العتيبي") and r.language == "ar" and r.duration_seconds == 1.4
    assert 'name="keyterms"' in seen["body"] and "الجلدية" in seen["body"] and "scribe_v2" in seen["body"]


async def test_azure_stt_resamples_and_uses_locale():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(params=dict(req.url.params), ctype=req.headers["content-type"], audio=req.content)
        return httpx.Response(200, json={"RecognitionStatus": "Success", "DisplayText": "مرحبا", "Duration": 15_000_000,
                                         "NBest": [{"Confidence": 0.9}]})

    stt = AzureSTT("k", "uaenorth", transport=httpx.MockTransport(handler))
    r = await stt.transcribe(tone_wav(48000, 0.5, 2), language="ar-EG")
    assert seen["params"] == {"language": "ar-EG", "format": "detailed"}
    with wave.open(io.BytesIO(seen["audio"])) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
    assert r.text == "مرحبا" and r.duration_seconds == 1.5


async def test_whisper_receives_vocabulary_as_hotwords():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = req.content.decode("utf-8", "ignore")
        return httpx.Response(200, json={"text": "x"})

    await WhisperHTTPSTT("http://stt/v1", transport=httpx.MockTransport(handler)).transcribe(
        b"RIFF", keywords=["سارة العتيبي", "الجلدية"])
    assert 'name="hotwords"' in seen["body"] and "سارة العتيبي الجلدية" in seen["body"]


async def test_neural_tts_and_cloning_requests():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, req.content[:2000]))
        if req.url.path == "/voices/clone":
            return httpx.Response(200, json={"id": "t1-sara", "seconds": 12.0})
        return httpx.Response(200, content=tone_wav(24000))

    tts = NeuralHTTPTTS("http://tts-neural:8002", transport=httpx.MockTransport(handler))
    r = await tts.synthesize("مرحبا", voice_id="t1-sara", language="ar")
    assert json.loads(seen[0][1])["engine"] == "neural" and r.sample_rate == 24000
    assert (await tts.clone("t1-sara", tone_wav(), "ref.wav"))["seconds"] == 12.0


def test_voice_resolution():
    azure = AgentDefinition(name="a", voice={"provider": "azure", "voice_id": "ar-SA-HamedNeural",
                                             "match_caller_dialect": True, "gender": "female"})
    assert resolve_voice(azure, "ar", "eg") == ("azure", "ar-EG-SalmaNeural")
    assert resolve_voice(azure, "ar", "kw") == ("azure", "ar-KW-NouraNeural")
    assert resolve_voice(azure, "en", "eg") == ("azure", "en-US-AvaMultilingualNeural")
    fixed = AgentDefinition(name="b", voice={"provider": "azure", "voice_id": "ar-AE-HamdanNeural"})
    assert resolve_voice(fixed, "ar", "eg") == ("azure", "ar-AE-HamdanNeural")
    eleven = AgentDefinition(name="c", voice={"provider": "elevenlabs", "voice_id": "VOICE1", "english_voice_id": None})
    assert resolve_voice(eleven, "en", None) == ("elevenlabs", "VOICE1")
    assert resolve_voice(AgentDefinition(name="d"), "ar", None) == ("local", "ar_JO-kareem-medium")


def test_stt_keywords_include_business_and_vocabulary():
    d = AgentDefinition(name="x", general={"business_name": "عيادة الشفاء"},
                        language_behavior={"vocabulary": ["سارة العتيبي", "الجلدية", "الجلدية"]})
    assert stt_keywords(d) == ["عيادة الشفاء", "سارة العتيبي", "الجلدية"]


class FakeTTS(TTSProvider):
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, *, voice_id, language, speed=1.0):
        self.calls.append((voice_id, language))
        return SynthesisResult(audio=tone_wav(24000, 0.1), sample_rate=24000, characters=len(text))

    async def health(self):
        return True


async def test_catalog_preview_and_dialect_voice_in_test_console(account, monkeypatch):
    from nexa.core.config import get_settings

    monkeypatch.setattr(get_settings(), "azure_speech_key", "k")
    fake = FakeTTS()
    registry.override("tts:azure", fake)
    catalog = (await account.get("/voices/catalog")).json()["providers"]
    azure = next(p for p in catalog if p["key"] == "azure")
    assert azure["configured"] and any(v["id"] == "ar-EG-SalmaNeural" for v in azure["voices"])
    assert not next(p for p in catalog if p["key"] == "elevenlabs")["configured"]

    r = await account.post("/voices/preview", {"provider": "azure", "voice_id": "ar-SA-HamedNeural", "language": "ar"})
    assert r.status_code == 200 and r.json()["audio_base64"]
    r = await account.post("/voices/preview", {"provider": "elevenlabs", "voice_id": "x", "language": "ar"})
    assert r.status_code == 503 and "not configured" in r.json()["error"]["message"]

    agent = (await account.post("/agents", {"template_key": "blank", "business_name": "ABC"})).json()
    cfg = {**agent["draft_config"], "voice": {"provider": "azure", "voice_id": "ar-SA-HamedNeural",
                                              "match_caller_dialect": True, "gender": "female"}}
    assert (await account.put(f"/agents/{agent['id']}/config", cfg)).status_code == 200
    registry.override("llm", __import__("nexa.providers.llm.scripted", fromlist=["ScriptedLLM"]).ScriptedLLM(["تمام"]))
    sid = (await account.post("/test/sessions?voice=true", {"agent_id": agent["id"]})).json()["session_id"]
    r = (await account.post(f"/test/sessions/{sid}/messages?voice=true", {"text": "عايز احجز معاد دلوقتي"})).json()
    assert r["result"]["dialect"] == "eg" and r["audio"][0]["audio_base64"]
    assert fake.calls[-1] == ("ar-EG-SalmaNeural", "ar")  # Egyptian caller hears an Egyptian voice


class FakeNeural(FakeTTS):
    name = "neural"

    def __init__(self):
        super().__init__()
        self.cloned: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def clone(self, voice_id, audio, filename):
        self.cloned[voice_id] = audio
        return {"id": voice_id, "seconds": 12.0}

    async def delete_voice(self, voice_id):
        self.deleted.append(voice_id)


def upload(account, name, consent="true", provider="neural", seconds=1.0):
    return account.client.post("/voices", headers=account.headers,
                                data={"name": name, "consent": consent, "provider": provider},
                                files={"file": ("recording.wav", tone_wav(24000, seconds), "audio/wav")})


async def test_voice_library_upload_list_use_rename_delete(account):
    neural = FakeNeural()
    registry.override("tts:neural", neural)
    r = await upload(account, "نورة", consent="false")
    assert r.status_code == 422 and "permission" in r.json()["error"]["message"]

    r = await upload(account, "نورة")
    assert r.status_code == 201, r.text
    voice = r.json()
    assert voice["name"] == "نورة" and voice["provider"] == "neural" and voice["seconds"] == 12.0
    assert voice["voice_id"] in neural.cloned
    assert (await upload(account, "نورة")).status_code == 409  # unique per business

    listing = (await account.get("/voices")).json()
    assert [v["name"] for v in listing["voices"]] == ["نورة"]
    assert {e["key"]: e["available"] for e in listing["engines"]}["neural"] is True
    rec = await account.get(f"/voices/{voice['id']}/recording")
    assert rec.status_code == 200 and rec.content.startswith(b"RIFF")

    catalog = (await account.get("/voices/catalog")).json()["providers"]
    neural_voices = next(p for p in catalog if p["key"] == "neural")["voices"]
    assert neural_voices[0] == {"id": voice["voice_id"], "name": "نورة (your voice)", "custom": True}

    agent = (await account.post("/agents", {"template_key": "blank", "business_name": "ABC"})).json()
    cfg = {**agent["draft_config"], "voice": {**agent["draft_config"]["voice"], "provider": "neural",
                                              "voice_id": voice["voice_id"]}}
    await account.put(f"/agents/{agent['id']}/config", cfg)
    r = await account.delete(f"/voices/{voice['id']}")
    assert r.status_code == 409 and agent["name"] in r.json()["error"]["message"]
    assert (await account.get("/voices")).json()["voices"][0]["used_by"] == [agent["name"]]

    r = await account.patch(f"/voices/{voice['id']}", {"name": "Noura - reception"})
    assert r.json()["name"] == "Noura - reception"

    cfg["voice"]["voice_id"] = "default"
    await account.put(f"/agents/{agent['id']}/config", cfg)
    assert (await account.delete(f"/voices/{voice['id']}")).status_code == 204
    assert neural.deleted == [voice["voice_id"]] and (await account.get("/voices")).json()["voices"] == []


async def test_voice_in_use_by_published_version_cannot_be_deleted(account):
    registry.override("tts:neural", FakeNeural())
    voice = (await upload(account, "Sara")).json()
    agent = (await account.post("/agents", {"template_key": "blank", "business_name": "ABC"})).json()
    cfg = {**agent["draft_config"], "voice": {**agent["draft_config"]["voice"], "provider": "neural",
                                              "voice_id": voice["voice_id"]}}
    await account.put(f"/agents/{agent['id']}/config", cfg)
    assert (await account.post(f"/agents/{agent['id']}/publish", {"notes": ""})).status_code == 201
    cfg["voice"]["voice_id"] = "default"  # draft changed, but live calls still use the voice
    await account.put(f"/agents/{agent['id']}/config", cfg)
    assert (await account.delete(f"/voices/{voice['id']}")).status_code == 409


async def test_voice_library_is_tenant_isolated(client, account):
    from tests.conftest import register

    registry.override("tts:neural", FakeNeural())
    voice = (await upload(account, "Private")).json()
    other = await register(client, "o@xyz.example.com", "Other")
    assert (await other.get("/voices")).json()["voices"] == []
    assert (await other.get(f"/voices/{voice['id']}/recording")).status_code == 404
    assert (await other.delete(f"/voices/{voice['id']}")).status_code == 404


async def test_elevenlabs_cloning(account, monkeypatch):
    from nexa.core.config import get_settings

    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "k")
    seen = {}

    def handler(req: httpx.Request):
        if req.url.path == "/v1/voices/add":
            seen["body"] = req.content.decode("utf-8", "ignore")
            return httpx.Response(200, json={"voice_id": "EL_NEW"})
        if req.url.path == "/v1/voices":
            return httpx.Response(200, json={"voices": [{"voice_id": "EL_NEW", "name": "Noura"},
                                                        {"voice_id": "EL_STOCK", "name": "Rachel"}]})
        return httpx.Response(404)

    registry.override("tts:elevenlabs", ElevenLabsTTS("k", transport=httpx.MockTransport(handler)))
    r = await upload(account, "Noura", provider="elevenlabs")
    assert r.status_code == 201 and r.json()["voice_id"] == "EL_NEW"
    assert 'name="name"' in seen["body"] and "Noura" in seen["body"] and 'name="files"' in seen["body"]
    voices = next(p for p in (await account.get("/voices/catalog")).json()["providers"] if p["key"] == "elevenlabs")["voices"]
    assert [v["id"] for v in voices] == ["EL_NEW", "EL_STOCK"] and voices[0]["name"] == "Noura (your voice)"


async def test_upload_when_neural_service_is_not_running(account):
    def unreachable(req: httpx.Request):
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=req)  # no --profile neural

    registry.override("tts:neural", NeuralHTTPTTS("http://tts-neural:8002", transport=httpx.MockTransport(unreachable)))
    listing = (await account.get("/voices")).json()
    assert {e["key"]: e["available"] for e in listing["engines"]}["neural"] is False
    r = await upload(account, "Noura")
    assert r.status_code == 503 and "--profile neural" in r.json()["error"]["message"]
    assert (await account.get("/voices")).json()["voices"] == []


async def test_upload_when_neural_service_drops_during_cloning(account):
    def handler(req: httpx.Request):
        if req.url.path == "/health":
            return httpx.Response(200, json={"engines": ["piper", "neural"]})
        raise httpx.ConnectError("connection reset", request=req)

    registry.override("tts:neural", NeuralHTTPTTS("http://tts-neural:8002", transport=httpx.MockTransport(handler)))
    r = await upload(account, "Noura")
    assert r.status_code == 503 and "could not be created" in r.json()["error"]["message"]
    assert (await account.get("/voices")).json()["voices"] == []


async def test_neural_voice_restored_from_saved_recording(account):
    registry.override("tts:neural", FakeNeural())
    voice = (await upload(account, "Noura")).json()
    service_has: set[str] = set()
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/voices/clone":
            service_has.add(voice["voice_id"])
            return httpx.Response(200, json={"id": voice["voice_id"], "seconds": 1.0})
        if voice["voice_id"] not in service_has:
            return httpx.Response(404, json={"detail": "unknown voice"})  # e.g. the service volume was reset
        return httpx.Response(200, content=tone_wav(24000))

    from nexa.services.voice_library import saved_recording

    tts = NeuralHTTPTTS("http://tts-neural:8002", transport=httpx.MockTransport(handler), restore=saved_recording)
    r = await tts.synthesize("مرحبا", voice_id=voice["voice_id"], language="ar")
    assert is_wav(r.audio) and calls == ["/synthesize", "/voices/clone", "/synthesize"]


async def test_audio_turn_passes_vocabulary_to_recognition(account):
    class FakeSTT(STTProvider):
        async def transcribe(self, audio, *, mime_type="audio/wav", language=None, prompt=None, keywords=None,
                         languages=None):
            self.keywords = keywords
            return TranscriptionResult(text="أبغى موعد", language="ar", duration_seconds=1.0)

    stt = FakeSTT()
    registry.override("stt", stt)
    registry.override("llm", __import__("nexa.providers.llm.scripted", fromlist=["ScriptedLLM"]).ScriptedLLM(["أكيد"]))
    agent = (await account.post("/agents", {"template_key": "blank", "business_name": "عيادة الشفاء"})).json()
    cfg = {**agent["draft_config"]}
    cfg["language_behavior"] = {**cfg["language_behavior"], "vocabulary": ["سارة العتيبي"]}
    await account.put(f"/agents/{agent['id']}/config", cfg)
    sid = (await account.post("/test/sessions", {"agent_id": agent["id"]})).json()["session_id"]
    r = await account.client.post(f"/test/sessions/{sid}/audio", headers=account.headers,
                                  files={"file": ("a.wav", tone_wav(16000), "audio/wav")}, data={"voice": "false"})
    assert r.status_code == 200, r.text
    assert stt.keywords == ["عيادة الشفاء", "سارة العتيبي"]


@pytest.mark.parametrize("provider", ["local", "neural", "elevenlabs", "azure"])
def test_provider_accepted_in_definition(provider):
    assert AgentDefinition(name="x", voice={"provider": provider}).voice.provider == provider
