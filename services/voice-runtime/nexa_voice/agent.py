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


@dataclass
class CallHandle:
    call_id: UUID
    tenant_id: UUID
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    language: str = "ar"


class NexaVoiceAgent(Agent):
    def __init__(self, handle: CallHandle, tts_for_language=None):
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
        if result.language and result.language != self.handle.language and self._tts_for_language:
            self.handle.language = result.language
            self._tts_for_language(result.language)
        return result

    async def llm_node(self, chat_ctx: llm.ChatContext, tools: list, model_settings: ModelSettings) -> AsyncIterable[str]:
        user_text = ""
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                user_text = item.text_content or ""
                break
        if not user_text.strip():
            return
        try:
            result = await self.run_turn(user_text)
        except Exception:
            log.exception("turn failed")
            yield "عذراً، حدث خلل. لحظة من فضلك." if self.handle.language == "ar" else "Sorry, something went wrong."
            return
        for reply in result.replies:
            yield reply + " "
            await asyncio.sleep(0)
