"""Deterministic LLM provider for tests and offline demos.

Returns pre-scripted responses in order. Each script item is either a string
(assistant text) or ``{"tool": name, "arguments": {...}}`` (a tool call), or a
list of such tool calls.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from nexa.providers.llm.base import ChatMessage, LLMProvider, LLMResponse, LLMUsage, ToolCall


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, script: list[Any] | None = None):
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def _next(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        item = self.script.pop(0) if self.script else "عذراً، لم أفهم. هل يمكنك التوضيح؟"
        if isinstance(item, str):
            return LLMResponse(content=item, usage=LLMUsage(10, 5), model="scripted")
        items = item if isinstance(item, list) else [item]
        calls = [
            ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=i["tool"], arguments=i.get("arguments", {}),
                     arguments_json=json.dumps(i.get("arguments", {})))
            for i in items
        ]
        return LLMResponse(content="", tool_calls=calls, usage=LLMUsage(10, 5), model="scripted")

    async def generate(self, messages, *, temperature=None, max_tokens=None, response_format=None) -> LLMResponse:
        return self._next(messages, None)

    async def generate_with_tools(self, messages, tools, *, temperature=None, max_tokens=None) -> LLMResponse:
        return self._next(messages, tools)

    async def stream(self, messages, *, temperature=None, max_tokens=None) -> AsyncIterator[str]:
        resp = self._next(messages, None)
        for word in resp.content.split(" "):
            yield word + " "
