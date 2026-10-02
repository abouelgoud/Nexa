"""The real-time voice agent: LiveKit handles audio, VAD, turn-taking and barge-in;
Nexa's ConversationRuntime handles every turn (language, workflow/LLM, tools, policies, logging)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from livekit.agents import Agent, llm
from livekit.agents.voice import ModelSettings

from nexa.core.db import get_sessionmaker
from nexa.runtime.session import ConversationRuntime, TurnResult

log = logging.getLogger("nexa.voice")


FILLERS = {"ar": "لحظة من فضلك.", "en": "One moment, please."}
FILLER_AFTER_SECONDS = 0.9


@dataclass
class CallHandle:
    call_id: UUID
    tenant_id: UUID
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    language: str = "ar"
    dialect: str | None = None
    thinking_fillers: bool = True


class NexaVoiceAgent(Agent):
    def __init__(self, handle: CallHandle, tts_for_language=None):
        """``tts_for_language(language, dialect)`` re-targets the voice when the caller's language/dialect changes."""
        # Instructions are unused: replies come from the Nexa runtime, never from a free-running model.
        super().__init__(instructions="Nexa runtime-driven agent")
        self.handle = handle
        self._tts_for_language = tts_for_language
        self.turns: list[TurnResult] = []

    async def run_turn(self, text: str, stt_meta: dict[str, Any] | None = None) -> TurnResult:
        async with get_sessionmaker()() as db:
            rt = await ConversationRuntime.load(db, self.handle.call_id, self.handle.tenant_id)
            if rt is None:
                raise RuntimeError("call not found")
            result = await rt.handle_user_text(text, stt=stt_meta)
            await db.commit()
        self.turns.append(result)
        self.handle.pending_actions.extend(a for a in result.actions if a.get("type") in ("transfer", "end_call"))
        if result.ended and not any(a.get("type") == "end_call" for a in self.handle.pending_actions):
            self.handle.pending_actions.append({"type": "end_call"})
        language = result.language or self.handle.language
        if (language, result.dialect) != (self.handle.language, self.handle.dialect):
            self.handle.language, self.handle.dialect = language, result.dialect
            if self._tts_for_language:
                self._tts_for_language(language, result.dialect)
        return result

    async def llm_node(self, chat_ctx: llm.ChatContext, tools: list, model_settings: ModelSettings) -> AsyncIterable[str]:
        user_text = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                user_text = item.text_content or ""
                break
        if not user_text.strip():
            return
        turn = asyncio.ensure_future(self.run_turn(user_text))
        if self.handle.thinking_fillers:
            # A person says "one moment" while checking the system instead of going silent.
            done, _ = await asyncio.wait({turn}, timeout=FILLER_AFTER_SECONDS)
            if not done:
                yield FILLERS.get(self.handle.language, FILLERS["ar"]) + " "
        try:
            result = await turn
        except Exception:
            log.exception("turn failed")
            yield "عذراً، حدث خلل. لحظة من فضلك." if self.handle.language == "ar" else "Sorry, something went wrong."
            return
        for reply in result.replies:
            yield reply + " "
            await asyncio.sleep(0)
