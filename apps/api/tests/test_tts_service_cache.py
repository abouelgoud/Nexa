"""services/tts: natural-voice phrases are rendered once and replayed from the cache."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi.testclient")
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "tts"))

import app as tts_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_repeated_phrases_come_from_the_cache(monkeypatch):
    calls = []

    def fake_synthesize(text, voice_id, language):
        calls.append((text, voice_id))
        return b"RIFF-" + text.encode(), 24000

    monkeypatch.setattr(tts_app, "ENGINES", ["neural"])
    monkeypatch.setattr(tts_app.neural, "synthesize", fake_synthesize)
    monkeypatch.setattr(tts_app.neural, "save_reference", lambda voice_id, data: {"seconds": 5.0})
    tts_app._cache.clear()
    client = TestClient(tts_app.app)
    body = {"text": "لحظة من فضلك.", "voice": "noura", "language": "ar", "engine": "neural"}

    first, second = client.post("/synthesize", json=body), client.post("/synthesize", json=body)
    assert first.headers["x-cache"] == "miss" and second.headers["x-cache"] == "hit"
    assert first.content == second.content and len(calls) == 1

    # A new recording for the voice must not replay the old voice's audio.
    client.post("/voices/clone", data={"voice_id": "noura"}, files={"file": ("r.wav", b"x" * 100)})
    assert client.post("/synthesize", json=body).headers["x-cache"] == "miss" and len(calls) == 2
