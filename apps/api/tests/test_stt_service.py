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
    monkeypatch.setattr(stt_app, "model", lambda: fake)
    return fake


def test_detected_language_outside_the_agents_languages_is_redone(whisper):
    out = stt_app._faster_whisper(b"audio", None, "prompt", None, ["ar", "en"])
    assert out["language"] == "ar" and out["segments"][0]["text"] == "نعم"
    assert whisper.calls == [None, "ar"]  # detected Persian, then the most likely allowed language


def test_single_language_agent_is_recognised_in_that_language(whisper):
    out = stt_app._faster_whisper(b"audio", None, "prompt", None, ["ar"])
    assert out["language"] == "ar" and whisper.calls == ["ar"]


def test_without_a_language_list_whisper_decides(whisper):
    assert stt_app._faster_whisper(b"audio", None, "prompt", None, None)["language"] == "fa"
