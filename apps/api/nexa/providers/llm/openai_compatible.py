"""OpenAI-compatible chat completions provider (vLLM serving Qwen3 by default).

Works with any server implementing ``/v1/chat/completions`` with tool calling
(vLLM ``--enable-auto-tool-choice --tool-call-parser hermes`` for Qwen3).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexa.providers.llm.base import ChatMessage, LLMError, LLMProvider, LLMResponse, LLMUsage, ToolCall

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Remove hidden reasoning blocks; they must never reach callers or the UI."""
    text = THINK_RE.sub("", text or "")
    if "<think>" in text:  # unterminated block (truncated generation)
        text = text.split("<think>")[0]
    return text.strip()


class OpenAICompatibleLLM(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self, base_url: str, model: str, api_key: str = "not-needed", timeout: float = 60.0,
        temperature: float = 0.3, max_tokens: int = 400, disable_thinking: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.disable_thinking = disable_thinking
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}, transport=transport
        )

    def _payload(self, messages: list[ChatMessage], temperature, max_tokens, **extra) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if self.disable_thinking:
            # Honoured by vLLM for Qwen3 chat templates; ignored by other servers.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload.update({k: v for k, v in extra.items() if v is not None})
        return payload

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        start = time.perf_counter()
        try:
            r = await self._client.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM server unreachable: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(f"LLM server error {r.status_code}: {r.text[:300]}")
        return r.json(), (time.perf_counter() - start) * 1000

    @staticmethod
    def _parse(data: dict[str, Any], latency_ms: float) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice.get("message", {})
        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
                err = None if isinstance(args, dict) else "arguments must be an object"
                args = args if isinstance(args, dict) else {}
            except json.JSONDecodeError as exc:
                args, err = {}, f"invalid JSON arguments: {exc.msg}"
            calls.append(ToolCall(id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", name=fn.get("name", ""),
                                  arguments=args, arguments_json=raw if isinstance(raw, str) else json.dumps(raw),
                                  parse_error=err))
        content = strip_reasoning(msg.get("content") or "")
        if not calls:
            calls = _parse_inline_tool_calls(content)
            if calls:
                content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content, tool_calls=calls, latency_ms=latency_ms, model=data.get("model", ""),
            usage=LLMUsage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            finish_reason=choice.get("finish_reason"),
        )

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_format=None) -> LLMResponse:
        data, latency = await self._post(self._payload(messages, temperature, max_tokens, response_format=response_format))
        return self._parse(data, latency)

    async def generate_with_tools(self, messages, tools, *, temperature=None, max_tokens=None) -> LLMResponse:
        payload = self._payload(messages, temperature, max_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data, latency = await self._post(payload)
        return self._parse(data, latency)

    async def stream(self, messages, *, temperature=None, max_tokens=None) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens, stream=True)
        in_think = False
        async with self._client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as r:
            if r.status_code >= 400:
                raise LLMError(f"LLM server error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                delta = json.loads(chunk)["choices"][0].get("delta", {}).get("content") or ""
                # Drop reasoning tokens from the stream.
                if "<think>" in delta:
                    in_think = True
                    delta = delta.split("<think>")[0]
                if in_think:
                    if "</think>" in delta:
                        in_think = False
                        delta = delta.split("</think>", 1)[1]
                    else:
                        continue
                if delta:
                    yield delta

    async def health(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_inline_tool_calls(content: str) -> list[ToolCall]:
    """Fallback for servers without a tool parser: Qwen/Hermes emit <tool_call>{json}</tool_call>."""
    calls = []
    for raw in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, flags=re.DOTALL):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        args = obj.get("arguments", {})
        calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=obj.get("name", ""),
                              arguments=args if isinstance(args, dict) else {}, arguments_json=json.dumps(args)))
    return calls
