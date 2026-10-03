"""Provider adapters: OpenAI-compatible LLM (vLLM/Qwen3), Whisper STT and Piper TTS over HTTP."""

import json

import httpx
import pytest

from nexa.providers.llm.base import ChatMessage, LLMError
from nexa.providers.llm.openai_compatible import OpenAICompatibleLLM, strip_reasoning
from nexa.providers.stt.whisper_http import WhisperHTTPSTT
from nexa.providers.tts.piper_http import PiperHTTPTTS


def llm_with(handler) -> tuple[OpenAICompatibleLLM, list]:
    seen = []

    def wrapped(req: httpx.Request):
        seen.append(json.loads(req.content))
        return handler(req)

    return OpenAICompatibleLLM("http://llm:8000/v1", "Qwen/Qwen3-8B", transport=httpx.MockTransport(wrapped)), seen


async def test_tool_calls_parsed_and_thinking_disabled():
    def handler(_):
        return httpx.Response(200, json={"model": "Qwen/Qwen3-8B", "choices": [{"finish_reason": "tool_calls", "message": {
            "content": "<think>hidden reasoning</think>", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "get_available_slots", "arguments": "{\"specialty_id\": 1}"}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    llm, seen = llm_with(handler)
    resp = await llm.generate_with_tools([ChatMessage("user", "أبغى موعد")], [{"type": "function", "function": {
        "name": "get_available_slots", "parameters": {"type": "object"}}}])
    assert resp.tool_calls[0].name == "get_available_slots" and resp.tool_calls[0].arguments == {"specialty_id": 1}
    assert resp.content == "" and resp.usage.total == 120
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[0]["tool_choice"] == "auto"


async def test_reasoning_switched_off_for_ollama_and_dropped_where_refused():
    """Ollama ignores chat_template_kwargs; reasoning_effort="none" is what stops Qwen3 thinking there.
    A server that refuses the value (e.g. some vLLM versions) gets it dropped, once."""
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append(body)
        if body.get("reasoning_effort") == "none" and len(seen) >= 2:
            return httpx.Response(400, json={"error": "reasoning_effort must be one of low, medium, high"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "أهلاً"}}], "usage": {}})

    llm = OpenAICompatibleLLM("http://localhost:11434/v1", "qwen3:4b", transport=httpx.MockTransport(handler))
    assert (await llm.generate([ChatMessage("user", "مرحبا")])).content == "أهلاً"
    assert seen[0]["reasoning_effort"] == "none" and seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert (await llm.generate([ChatMessage("user", "مرحبا")])).content == "أهلاً"  # refused, then retried without
    assert "reasoning_effort" not in seen[2]
    await llm.generate([ChatMessage("user", "مرحبا")])
    assert len(seen) == 4 and "reasoning_effort" not in seen[3]  # remembered


async def test_hidden_reasoning_never_returned():
    assert strip_reasoning("<think>secret plan</think>\nأهلاً") == "أهلاً"
    assert strip_reasoning("answer <think>truncated") == "answer"


async def test_inline_hermes_tool_calls_fallback():
    def handler(_):
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '<tool_call>{"name": "end_call", "arguments": {}}</tool_call>'}}]})

    llm, _ = llm_with(handler)
    resp = await llm.generate_with_tools([ChatMessage("user", "bye")], [])
    assert resp.tool_calls[0].name == "end_call" and resp.content == ""


async def test_invalid_arguments_flagged():
    def handler(_):
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "x", "function": {"name": "find_patient", "arguments": "{not json"}}]}}]})

    llm, _ = llm_with(handler)
    resp = await llm.generate_with_tools([ChatMessage("user", "x")], [])
    assert resp.tool_calls[0].parse_error


async def test_server_errors_raise_llm_error():
    llm, _ = llm_with(lambda _: httpx.Response(503, text="overloaded"))
    with pytest.raises(LLMError):
        await llm.generate([ChatMessage("user", "x")])


async def test_streaming_drops_reasoning_tokens():
    chunks = ["<think>", "plan", "</think>", "أهلاً", " وسهلاً"]
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks) + "data: [DONE]\n\n"
    llm, _ = llm_with(lambda _: httpx.Response(200, text=body))
    out = "".join([t async for t in llm.stream([ChatMessage("user", "x")])])
    assert out == "أهلاً وسهلاً"


async def test_whisper_stt():
    def handler(req: httpx.Request):
        assert req.url.path == "/v1/audio/transcriptions"
        return httpx.Response(200, json={"text": " أبغى أحجز موعد ", "language": "ar", "duration": 2.5,
                                         "segments": [{"text": "أبغى أحجز موعد", "start": 0, "end": 2.5}]})

    stt = WhisperHTTPSTT("http://stt:8001/v1", transport=httpx.MockTransport(handler))
    r = await stt.transcribe(b"RIFF....", mime_type="audio/webm")
    assert r.text == "أبغى أحجز موعد" and r.language == "ar" and r.segments[0].end_ms == 2500


async def test_piper_tts():
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        assert body["voice"] == "ar_JO-kareem-medium"
        return httpx.Response(200, content=b"RIFFWAVE", headers={"content-type": "audio/wav", "x-sample-rate": "22050"})

    tts = PiperHTTPTTS("http://tts:8002", transport=httpx.MockTransport(handler))
    r = await tts.synthesize("مرحبا", voice_id="ar_JO-kareem-medium", language="ar")
    assert r.audio == b"RIFFWAVE" and r.characters == 5


async def test_whisper_echo_of_its_hint_is_not_caller_speech():
    """Near-silence can make Whisper output its own prompt; that must not become a caller turn."""
    replies = iter(["Phone call in Arabic and English.", "مكالمة هاتفية", "عيادة الجلدية", "أبغى موعد جلدية"])

    def handler(_):
        return httpx.Response(200, json={"text": next(replies), "language": "ar", "duration": 1.0,
                                         "segments": [{"text": "x", "start": 0, "end": 1}]})

    stt = WhisperHTTPSTT("http://stt:8001/v1", transport=httpx.MockTransport(handler))
    assert (await stt.transcribe(b"RIFF")).text == ""  # echo of the service's default hint
    r = await stt.transcribe(b"RIFF", prompt="مكالمة هاتفية. Phone call in Arabic and English.")
    assert r.text == "" and r.segments == []
    assert (await stt.transcribe(b"RIFF", keywords=["عيادة الجلدية", "د. سارة"])).text == ""  # hotwords echo
    assert (await stt.transcribe(b"RIFF", keywords=["جلدية"])).text == "أبغى موعد جلدية"  # real speech kept
