"""LLM provider interface. The application never talks to a model server directly."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments_json}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name and self.role == "tool":
            msg["name"] = self.name
        return msg


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    arguments_json: str = "{}"
    parse_error: str | None = None


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    model: str = ""
    finish_reason: str | None = None


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(
        self, messages: list[ChatMessage], *, temperature: float | None = None, max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def stream(
        self, messages: list[ChatMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    async def generate_with_tools(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], *, temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    async def health(self) -> bool:
        return True
