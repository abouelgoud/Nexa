"""services/stt: recognition never picks a language the agent doesn't speak."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("faster_whisper")
_path = Path(__file__).resolve().parents[3] / "services" / "stt" / "app.py"
_spec = importlib.util.spec_from_file_location("nexa_stt_service", _path)
stt_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stt_app)


class FakeWhisper:
    """Detects Persian for a short Arabic phrase, as Whisper sometimes does."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kw):
        self.calls.append(language)
        detected = language or "fa"
        info = SimpleNamespace(language=detected, language_probability=0.6, duration=1.0,
                               all_language_probs=[("fa", 0.55), ("ar", 0.35), ("en", 0.1)])
        text = {"ar": "نعم", "fa": "نم"}.get(detected, "yes")
        return iter([SimpleNamespace(start=0.0, end=1.0, text=text, avg_logprob=-0.2)]), info


@pytest.fixture
def whisper(monkeypatch):
    fake = FakeWhisper()
    detected = []
    monkeypatch.setattr(stt_app, "model", lambda: fake)
    monkeypatch.setattr(stt_app, "_samples", lambda audio: audio)
    # The small language model: Persian most likely for a short Arabic phrase, as Whisper sometimes thinks.
    monkeypatch.setattr(stt_app, "detect", lambda samples: detected.append(samples) or [("fa", 0.55), ("ar", 0.35),
                                                                                       ("en", 0.1)])
    fake.detected = detected
    return fake


def test_language_is_picked_first_so_the_large_model_runs_once(whisper):
    out = stt_app._faster_whisper(b"audio", None, "prompt", None, ["ar", "en"])
    assert out["language"] == "ar" and out["segments"][0]["text"] == "نعم"
    assert whisper.calls == ["ar"]  # one pass, in the most likely of the agent's languages (not Persian)
    assert len(whisper.detected) == 1


def test_single_language_agent_is_recognised_in_that_language(whisper):
    out = stt_app._faster_whisper(b"audio", None, "prompt", None, ["ar"])
    assert out["language"] == "ar" and whisper.calls == ["ar"] and not whisper.detected


def test_a_given_language_is_used_as_is(whisper):
    assert stt_app._faster_whisper(b"audio", "en", "prompt", None, ["ar", "en"])["language"] == "en"
    assert not whisper.detected


def test_without_a_language_list_the_most_likely_language_is_used(whisper):
    assert stt_app._faster_whisper(b"audio", None, "prompt", None, None)["language"] == "fa"


def test_without_the_small_model_the_large_one_detects(whisper, monkeypatch):
    monkeypatch.setattr(stt_app, "LID_MODEL", "")
    out = stt_app._faster_whisper(b"audio", None, "prompt", None, ["ar", "en"])
    assert out["language"] == "ar" and whisper.calls == [None, "ar"]  # detected Persian, redone in Arabic
