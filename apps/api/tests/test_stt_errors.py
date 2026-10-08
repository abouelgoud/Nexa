"""When speech recognition fails, the user is told why (not running / still loading / too slow)."""

import httpx
import pytest

from nexa.providers.stt.base import STTError
from nexa.providers.stt.whisper_http import WhisperHTTPSTT


async def _reason(handler) -> str:
    stt = WhisperHTTPSTT("http://stt:8001/v1", transport=httpx.MockTransport(handler), timeout=5)
    with pytest.raises(STTError) as info:
        await stt.transcribe(b"RIFF....", mime_type="audio/wav")
    return info.value.reason


async def test_failure_reasons():
    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    assert await _reason(refused) == "unreachable"
    assert await _reason(slow) == "timeout"
    assert await _reason(lambda r: httpx.Response(503, text="loading: model is still loading")) == "loading"
    assert await _reason(lambda r: httpx.Response(400, text="could not decode audio")) == "failed"
