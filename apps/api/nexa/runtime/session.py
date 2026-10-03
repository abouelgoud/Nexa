"""VoiceSession: the per-call conversation runtime shared by browser tests and phone calls.

Each turn: normalize -> detect language/dialect -> policy checks (human handoff)
-> workflow engine or LLM-with-tools loop -> output guard -> persist transcript,
tool executions, events and usage. State is persisted in ``conversations`` so any
API/voice worker process can continue the call.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexa.core.config import get_settings
from nexa.core.observability import CALLS, LLM_LATENCY, LLM_TTFT, TURN_LATENCY
from nexa.knowledge.service import retrieve
from nexa.models import (
    AgentVersion,
    Call,
    CallEvent,
    CallParticipant,
    Conversation,
    Message,
    Transcript,
    WorkflowExecution,
)
from nexa.nlp.arabic import normalize_text
from nexa.nlp.intents import classify_yes_no, is_human_request, keyword_intent
from nexa.nlp.language import SessionDialectTracker, detect_language
from nexa.providers.llm.base import ChatMessage, LLMError, LLMProvider, ToolCall
from nexa.providers.registry import get_llm
from nexa.runtime.prompt import build_system_prompt
from nexa.schemas.agent_definition import AgentDefinition, render_greeting
from nexa.schemas.tool_definition import DatabaseToolConfig, RestToolConfig
from nexa.schemas.workflow import WorkflowGraph
from nexa.services.hours import is_open, local_now
from nexa.services.usage import record_usage
from nexa.tools.executor import ToolContext, ToolExecutor, ToolResult
from nexa.workflow.engine import WorkflowEngine, new_state

HISTORY_LIMIT = 24
SUCCESS_CLAIMS = re.compile(
    r"(تم\s+(?:ال)?(?:حجز|إلغاء|الغاء|تأكيد|تعديل|تغيير|إرسال|ارسال)|حجزت\s+لك|ألغيت|الغيت|"
    r"\b(?:has been|is now|have been|i've|i have)\s+(?:booked|cancelled|canceled|rescheduled|confirmed|sent)\b|"
    r"\byour (?:appointment|booking|order) is (?:booked|confirmed|cancelled|canceled)\b)",
    re.IGNORECASE,
)
FALLBACK = {
    "ar": "عذراً، واجهت مشكلة في معالجة طلبك.",
    "en": "Sorry, I had a problem processing your request.",
}
UNCONFIRMED = {
    "ar": "لم يتم تنفيذ الطلب بعد. هل تريد أن أكمل؟",
    "en": "That hasn't been completed yet. Would you like me to go ahead?",
}
TRANSFERRING = {"ar": "لحظة من فضلك، بحولك على أحد الموظفين.", "en": "One moment please, I'm transferring you to a staff member."}
OFFER_HUMAN = {"ar": "يبدو إني ما قدرت أساعدك بالشكل المطلوب. تحب أحولك على أحد الموظفين؟",
               "en": "It seems I couldn't help as expected. Would you like me to transfer you to a staff member?"}


@dataclass
class VoiceSession:
    """Serializable conversation state (stored in conversations.state)."""

    session_id: str
    tenant_id: str
    agent_id: str
    agent_version_id: str
    caller_number: str | None = None
    channel: str = "web"
    language: str | None = None
    dialect: str | None = None
    dialect_confidence: float = 0.0
    dialect_state: dict[str, Any] = field(default_factory=dict)
    conversation_state: dict[str, Any] = field(default_factory=dict)
    workflow_state: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    failures: int = 0
    offered_handoff: bool = False
    turn: int = 0
    ended: bool = False

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> VoiceSession:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class TurnResult:
    replies: list[str] = field(default_factory=list)
    language: str | None = None
    dialect: str | None = None
    dialect_confidence: float = 0.0
    dialect_scores: dict[str, float] = field(default_factory=dict)
    code_switching: bool = False
    intent: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    workflow: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: dict[str, float] = field(default_factory=dict)
    ended: bool = False
    transferred: bool = False
    normalized_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _args_hash(name: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(f"{name}:{json.dumps(args, sort_keys=True, default=str)}".encode()).hexdigest()[:16]


class ConversationRuntime:
    def __init__(self, db: AsyncSession, call: Call, conversation: Conversation, version: AgentVersion,
                 llm: LLMProvider | None = None):
        self.db = db
        self.call = call
        self.conversation = conversation
        self.version = version
        self.snapshot = version.config
        self.definition = AgentDefinition.model_validate(self.snapshot["definition"])
        self.session = VoiceSession.from_state(conversation.state)
        self._llm = llm
        self.now = local_now(self.definition)
        self.executor = ToolExecutor(ToolContext(db=db, tenant_id=call.tenant_id, snapshot=self.snapshot,
                                                 call_id=call.id, agent_id=call.agent_id, now=self.now))

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = get_llm()
        return self._llm

    @property
    def lang(self) -> str:
        if self.definition.language_behavior.mode == "fixed":
            return self.definition.language_behavior.primary_language
        lang = self.session.language or self.definition.language_behavior.primary_language
        return lang if lang in self.definition.languages else self.definition.languages[0]

    @property
    def workflow_mode(self) -> bool:
        return self.definition.execution_mode == "workflow" and bool(self.snapshot.get("workflow"))

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    async def start(cls, db: AsyncSession, *, tenant_id: UUID, agent_id: UUID, version: AgentVersion, channel: str,
                    is_test: bool, caller_number: str | None = None, to_number: str | None = None,
                    external_id: str | None = None, phone_number_id: UUID | None = None,
                    llm: LLMProvider | None = None) -> tuple[ConversationRuntime, TurnResult]:
        defn = AgentDefinition.model_validate(version.config["definition"])
        call = Call(tenant_id=tenant_id, agent_id=agent_id, agent_version_id=version.id, channel=channel,
                    is_test=is_test, from_number=caller_number, to_number=to_number, external_id=external_id,
                    phone_number_id=phone_number_id, status="active", metrics={})
        db.add(call)
        await db.flush()
        db.add(CallParticipant(tenant_id=tenant_id, call_id=call.id, role="caller", identity=caller_number or "web-user"))
        db.add(CallParticipant(tenant_id=tenant_id, call_id=call.id, role="agent", identity=f"agent:{agent_id}"))
        session = VoiceSession(session_id=str(call.id), tenant_id=str(tenant_id), agent_id=str(agent_id),
                               agent_version_id=str(version.id), caller_number=caller_number, channel=channel,
                               language=defn.language_behavior.primary_language)
        conv = Conversation(tenant_id=tenant_id, call_id=call.id, state=asdict(session))
        db.add(conv)
        await db.flush()
        rt = cls(db, call, conv, version, llm)
        result = TurnResult(language=rt.lang)
        if defn.privacy.consent_required and defn.privacy.consent_message.strip():
            result.replies.append(defn.privacy.consent_message.strip())
        if rt.workflow_mode:
            graph = WorkflowGraph.model_validate(rt.snapshot["workflow"]["graph"])
            rt.session.workflow_state = new_state(rt._base_variables())
            out = await WorkflowEngine(graph, rt._deps(result), rt.lang, rt.now).start(rt.session.workflow_state)
            result.replies.extend(out.utterances)
            rt._apply_workflow_output(result, out)
            db.add(WorkflowExecution(tenant_id=tenant_id, call_id=call.id,
                                     workflow_id=UUID(rt.snapshot["workflow"]["id"]), status="running"))
        else:
            greeting = render_greeting(defn, rt.lang)
            if greeting:
                result.replies.append(greeting)
                rt.session.history.append({"role": "assistant", "content": greeting})
        CALLS.labels(channel).inc()
        rt._event("call_started", {"channel": channel, "is_test": is_test, "agent_version": version.version_number,
                                   "mode": defn.execution_mode})
        for reply in result.replies:
            rt._store_message("assistant", reply)
        await rt._finish_turn(result)
        return rt, result

    @classmethod
    async def load(cls, db: AsyncSession, call_id: UUID, tenant_id: UUID, llm: LLMProvider | None = None,
                   lock: bool = True) -> ConversationRuntime | None:
        call = await db.get(Call, call_id)
        if call is None or call.tenant_id != tenant_id:
            return None
        q = select(Conversation).where(Conversation.call_id == call.id)
        if lock:
            q = q.with_for_update()
        conv = await db.scalar(q)
        version = await db.get(AgentVersion, call.agent_version_id)
        if conv is None or version is None:
            return None
        await db.refresh(conv)
        return cls(db, call, conv, version, llm)

    async def end(self, reason: str = "caller_hangup") -> None:
        if self.session.ended:
            return
        self.session.ended = True
        self.call.ended_at = datetime.now(UTC)
        started = self.call.started_at or self.call.ended_at
        self.call.duration_seconds = max(0.0, (self.call.ended_at - started).total_seconds())
        if self.call.status == "active":
            self.call.status = "completed"
        self.call.outcome = self.call.outcome or await self._outcome()
        record_usage(self.db, self.call.tenant_id, "call_seconds", self.call.duration_seconds or 0,
                     call_id=self.call.id, agent_id=self.call.agent_id)
        self._event("call_ended", {"reason": reason, "outcome": self.call.outcome})
        if not self.definition.privacy.store_transcript:
            self.session.history = []
        await self._save()

    async def _outcome(self) -> str:
        from nexa.models import ToolExecution

        rows = (await self.db.scalars(select(ToolExecution).where(ToolExecution.call_id == self.call.id))).all()
        if self.call.status == "transferred":
            return "transferred"
        writes = {name for name, e in self.executor.tools.items() if self._is_write(e["parsed"])}
        if any(r.status == "succeeded" and r.tool_name in writes for r in rows):
            return "task_completed"
        if any(r.status == "failed" for r in rows):
            return "failed"
        if any(r.status == "succeeded" and r.tool_name == "search_knowledge" for r in rows):
            return "info_provided"
        return "completed"

    # ------------------------------------------------------------------ turns
    async def handle_user_text(self, text: str, *, stt: dict[str, Any] | None = None) -> TurnResult:
        t0 = time.perf_counter()
        result = TurnResult()
        if self.session.ended:
            result.ended = True
            return result
        original = text.strip()
        normalized = normalize_text(original)
        result.normalized_text = normalized
        allowed = [d for d in self.definition.arabic_dialects]
        info = detect_language(normalized, allowed or None)
        tracker = SessionDialectTracker(self.session.dialect_state)
        dialect, conf = tracker.update(info) if info.language != "unknown" else tracker.best()
        self.session.dialect_state = tracker.to_state()
        if info.language in ("ar", "en"):
            self.session.language = info.language
        self.session.dialect, self.session.dialect_confidence = dialect, conf
        result.language, result.dialect, result.dialect_confidence = self.lang, dialect, round(conf, 3)
        result.dialect_scores = {k: round(v, 3) for k, v in info.dialect_scores.items()}
        result.code_switching = info.code_switching
        self.session.turn += 1
        self._store_message("user", original, normalized=normalized, language=info.language, dialect=info.dialect,
                            meta={"dialect_scores": result.dialect_scores, "code_switching": info.code_switching,
                                  "stt": stt or {}})
        self._event("user_turn", {"language": info.language, "dialect": info.dialect,
                                  "dialect_confidence": round(info.dialect_confidence, 3),
                                  "code_switching": info.code_switching})
        if not original:
            await self._finish_turn(result)
            return result

        handled = await self._policy_checks(original, result)
        if not handled:
            if self.workflow_mode:
                await self._workflow_turn(original, result)
            else:
                await self._agent_turn(original, result)
        result.latency_ms["turn_total"] = round((time.perf_counter() - t0) * 1000, 1)
        for reply in result.replies:
            self._store_message("assistant", reply, meta={"turn_ms": result.latency_ms["turn_total"]})
        TURN_LATENCY.labels("workflow" if self.workflow_mode else "agent").observe(result.latency_ms["turn_total"] / 1000)
        await self._finish_turn(result)
        return result

    async def _policy_checks(self, text: str, result: TurnResult) -> bool:
        """Deterministic rules that run before any model: explicit human requests and handoff offers."""
        h = self.definition.handoff
        handoff_on = h.enabled and self.definition.policies.human_handoff_enabled
        if self.session.offered_handoff:
            self.session.offered_handoff = False
            answer = classify_yes_no(text)
            if answer == "yes" and handoff_on:
                await self._transfer("caller accepted handoff offer", result)
                return True
            if answer == "no":
                self.session.failures = 0
                result.replies.append("تمام، كيف أقدر أساعدك؟" if self.lang == "ar" else "Okay, how can I help?")
                return True
        if handoff_on and h.on_explicit_request and is_human_request(text):
            result.intent = "human_handoff"
            await self._transfer("caller asked for a human", result)
            return True
        return False

    async def _transfer(self, reason: str, result: TurnResult) -> None:
        tr = await self.executor.execute("transfer_call", {"reason": reason}, source="policy", confirmed=True)
        result.tool_calls.append(tr.as_dict())
        if tr.ok and tr.action:
            result.replies.append(TRANSFERRING[self.lang])
            result.actions.append(tr.action)
        else:
            result.replies.append(tr.error or FALLBACK[self.lang])

    # ------------------------------------------------------------------ workflow mode
    def _base_variables(self) -> dict[str, Any]:
        return {"greeting": render_greeting(self.definition, self.lang),
                "business_name": self.definition.general.business_name,
                "caller_number": self.session.caller_number, "today": self.now.date().isoformat()}

    def _deps(self, result: TurnResult):
        rt = self

        class Deps:
            async def run_tool(self, name: str, args: dict[str, Any], confirmed: bool) -> ToolResult:
                r = await rt.executor.execute(name, args, source="workflow", confirmed=confirmed)
                result.tool_calls.append(r.as_dict())
                return r

            async def search_knowledge(self, query: str) -> dict[str, Any]:
                return await rt._knowledge_answer(query, result)

            async def classify_intent(self, text: str, intents: dict[str, list[str]]) -> str | None:
                intent = keyword_intent(text, intents)
                if intent is None:
                    intent = await rt._llm_classify(text, list(intents))
                result.intent = intent
                return intent

            async def choose_option(self, text: str, labels: list[str]) -> int | None:
                return await rt._llm_choose(text, labels)

        return Deps()

    async def _workflow_turn(self, text: str, result: TurnResult) -> None:
        graph = WorkflowGraph.model_validate(self.snapshot["workflow"]["graph"])
        state = self.session.workflow_state or new_state(self._base_variables())
        engine = WorkflowEngine(graph, self._deps(result), self.lang, self.now)
        if state.get("status") in ("completed", "transferred", "failed"):
            result.replies.append("شكراً لك." if self.lang == "ar" else "Thank you.")
            return
        out = await engine.handle_input(state, text)
        self.session.workflow_state = state
        result.replies.extend(out.utterances)
        self._apply_workflow_output(result, out)
        if any(not r.ok and r.status != "confirmation_required" for r in out.tool_results):
            self.session.failures += 1
        else:
            self.session.failures = 0

    def _apply_workflow_output(self, result: TurnResult, out) -> None:
        state = self.session.workflow_state or {}
        result.actions.extend(a for a in out.actions if a)
        result.events.extend(out.events)
        for ev in out.events:
            self._event(ev["type"], ev)
        result.workflow = {"current": state.get("current"), "status": state.get("status"),
                           "path": state.get("path", [])[-15:], "variables": _public_vars(state.get("variables", {}))}

    async def _knowledge_answer(self, query: str, result: TurnResult) -> dict[str, Any]:
        kb_ids = [UUID(str(k)) for k in self.definition.knowledge_base_ids]
        t0 = time.perf_counter()
        hits = await retrieve(self.db, self.call.tenant_id, kb_ids, query, 3)
        result.latency_ms["retrieval"] = round((time.perf_counter() - t0) * 1000, 1)
        if not hits:
            return {"found": False, "answer": "", "results": []}
        context = "\n\n".join(f"[{i + 1}] {h['content']}" for i, h in enumerate(hits))
        answer = None
        try:
            resp = await self.llm.generate([
                ChatMessage("system", "Answer the caller's question using ONLY the sources below, in "
                            f"{'Arabic' if self.lang == 'ar' else 'English'}, in one or two short spoken sentences. "
                            "If the sources do not contain the answer reply exactly NO_ANSWER.\n\nSources:\n" + context),
                ChatMessage("user", query),
            ], max_tokens=150, temperature=0.1)
            self._llm_usage(resp, "knowledge_answer", result)
            answer = resp.content.strip()
        except LLMError as exc:
            self._event("llm_error", {"error": str(exc)[:300], "purpose": "knowledge_answer"})
        if answer == "NO_ANSWER" or (answer is not None and "NO_ANSWER" in answer):
            return {"found": False, "answer": "", "results": hits}
        if not answer:
            # No model available: read the best matching passage (grounded, never invented).
            answer = hits[0]["content"].split("\n", 1)[-1][:350]
        return {"found": True, "answer": answer, "results": hits,
                "citations": [{"document_id": h["document_id"], "chunk_id": h["chunk_id"]} for h in hits]}

    async def _llm_classify(self, text: str, labels: list[str]) -> str | None:
        try:
            resp = await self.llm.generate([
                ChatMessage("system", "Classify the caller's message into exactly one of these intents: "
                            + ", ".join(labels) + ". Reply with the intent name only, or 'unknown'."),
                ChatMessage("user", text),
            ], max_tokens=10, temperature=0)
        except LLMError:
            return None
        label = resp.content.strip().lower().strip(".")
        return label if label in labels else None

    async def _llm_choose(self, text: str, labels: list[str]) -> int | None:
        options = "\n".join(f"{i + 1}. {label}" for i, label in enumerate(labels))
        try:
            resp = await self.llm.generate([
                ChatMessage("system", "Which option did the caller choose? Options:\n" + options +
                            "\nReply with the option number only, or 0 if unclear."),
                ChatMessage("user", text),
            ], max_tokens=5, temperature=0)
        except LLMError:
            return None
        m = re.search(r"\d+", resp.content)
        if not m:
            return None
        n = int(m.group()) - 1
        return n if 0 <= n < len(labels) else None

    # ------------------------------------------------------------------ agent (LLM) mode
    def _is_write(self, td) -> bool:
        cfg = td.typed_config()
        if isinstance(cfg, DatabaseToolConfig):
            return cfg.operation in ("create_record", "update_record", "delete_record")
        if isinstance(cfg, RestToolConfig):
            return cfg.method != "GET"
        return td.requires_confirmation

    async def _agent_turn(self, text: str, result: TurnResult) -> None:
        s = self.session
        user_said_yes = classify_yes_no(text) == "yes"
        system = build_system_prompt(self.definition, self.now, s.language, s.dialect, s.dialect_confidence,
                                     is_open(self.definition))
        s.history.append({"role": "user", "content": text})
        messages = [ChatMessage("system", system)] + [_from_hist(m) for m in s.history[-HISTORY_LIMIT:]]
        # Never start the window on an orphan tool result.
        while len(messages) > 1 and messages[1].role == "tool":
            messages.pop(1)
        tools = self.executor.llm_tools()
        turn_results: list[ToolResult] = []
        final: str | None = None
        for _ in range(get_settings().max_agent_tool_iterations):
            t0 = time.perf_counter()
            try:
                resp = await self.llm.generate_with_tools(messages, tools)
            except LLMError as exc:
                self._event("llm_error", {"error": str(exc)[:300]})
                s.failures += 1
                final = FALLBACK[self.lang]
                break
            result.latency_ms.setdefault("llm_first_response", round((time.perf_counter() - t0) * 1000, 1))
            self._llm_usage(resp, "agent_turn", result)
            if not resp.tool_calls:
                final = resp.content.strip()
                break
            assistant = ChatMessage("assistant", resp.content or "", tool_calls=resp.tool_calls)
            messages.append(assistant)
            s.history.append(_to_hist(assistant))
            for tc in resp.tool_calls:
                tr = await self._execute_llm_tool(tc, user_said_yes)
                turn_results.append(tr)
                result.tool_calls.append(tr.as_dict())
                if tr.action:
                    result.actions.append(tr.action)
                tool_msg = ChatMessage("tool", json.dumps(tr.for_llm(), ensure_ascii=False, default=str),
                                       tool_call_id=tc.id, name=tc.name)
                messages.append(tool_msg)
                s.history.append(_to_hist(tool_msg))
        if final is None:
            final = FALLBACK[self.lang]
            s.failures += 1
        final = self._guard_output(final, turn_results)
        if any(r.status == "failed" for r in turn_results) or final == FALLBACK[self.lang]:
            s.failures += 1
        elif turn_results or final:
            s.failures = 0 if not any(r.status == "rejected" for r in turn_results) else s.failures
        if final:
            result.replies.append(final)
            s.history.append({"role": "assistant", "content": final})
        if any(a.get("type") == "transfer" for a in result.actions):
            return
        h = self.definition.handoff
        if (h.enabled and h.on_low_confidence and self.definition.policies.human_handoff_enabled
                and s.failures >= get_settings().handoff_failure_threshold):
            s.offered_handoff = True
            s.failures = 0
            result.replies.append(OFFER_HUMAN[self.lang])
            self._event("handoff_offered", {"reason": "low_confidence"})

    async def _execute_llm_tool(self, tc: ToolCall, user_said_yes: bool) -> ToolResult:
        s = self.session
        if tc.parse_error:
            return ToolResult(status="rejected", tool_name=tc.name, error=tc.parse_error, error_code="invalid_arguments")
        entry = self.executor.tools.get(tc.name)
        confirmed = False
        if entry and self.executor.needs_confirmation(entry["parsed"]):
            from nexa.tools.validation import coerce_arguments

            args = coerce_arguments(entry["parsed"].input_schema, tc.arguments, self.now.date())
            h = _args_hash(tc.name, args)
            pending = s.pending_confirmation
            # Confirmation is a business rule: the caller must have said yes, in this turn, to exactly this action.
            confirmed = bool(pending and pending.get("hash") == h and pending.get("turn") == s.turn - 1
                             and user_said_yes)
            tr = await self.executor.execute(tc.name, tc.arguments, source="llm", confirmed=confirmed)
            if tr.status == "confirmation_required":
                s.pending_confirmation = {"tool": tc.name, "hash": h, "turn": s.turn}
            elif confirmed:
                s.pending_confirmation = None
            return tr
        return await self.executor.execute(tc.name, tc.arguments, source="llm")

    def _guard_output(self, text: str, turn_results: list[ToolResult]) -> str:
        """Never claim an external action succeeded unless a write action succeeded this turn."""
        if not text or not SUCCESS_CLAIMS.search(text):
            return text
        writes = {n for n, e in self.executor.tools.items() if self._is_write(e["parsed"])}
        if any(r.ok and r.tool_name in writes for r in turn_results):
            return text
        self._event("output_guard", {"blocked": text[:300]})
        return UNCONFIRMED[self.lang]

    def _llm_usage(self, resp, purpose: str, result: TurnResult) -> None:
        LLM_LATENCY.labels(purpose).observe(resp.latency_ms / 1000)
        if resp.ttft_ms is not None:
            LLM_TTFT.observe(resp.ttft_ms / 1000)
        if resp.usage.total:
            record_usage(self.db, self.call.tenant_id, "llm_tokens", resp.usage.total, call_id=self.call.id,
                         agent_id=self.call.agent_id, meta={"purpose": purpose, "model": resp.model})
        self._event("llm", {"purpose": purpose, "model": resp.model, "tokens": resp.usage.total,
                            "tool_calls": [tc.name for tc in resp.tool_calls], "finish_reason": resp.finish_reason},
                    latency=resp.latency_ms)

    # ------------------------------------------------------------------ persistence
    def _store_message(self, role: str, text: str, *, normalized: str | None = None, language: str | None = None,
                       dialect: str | None = None, meta: dict[str, Any] | None = None) -> None:
        keep = self.definition.privacy.store_transcript
        self.conversation.turn_count += 1
        seq = self.conversation.turn_count
        self.db.add(Message(tenant_id=self.call.tenant_id, conversation_id=self.conversation.id, role=role,
                            content=text if keep else "", original_text=text if keep else None,
                            normalized_text=(normalized or normalize_text(text)) if keep else None,
                            language=language or self.lang, dialect=dialect, meta=meta or {}, seq=seq))
        if keep:
            self.db.add(Transcript(tenant_id=self.call.tenant_id, call_id=self.call.id,
                                   speaker="caller" if role == "user" else "agent", original_text=text,
                                   normalized_text=normalized or normalize_text(text), language=language or self.lang,
                                   dialect=dialect, dialect_scores=(meta or {}).get("dialect_scores", {})))

    def _event(self, event_type: str, payload: dict[str, Any], latency: float | None = None) -> None:
        self.db.add(CallEvent(tenant_id=self.call.tenant_id, call_id=self.call.id, event_type=event_type,
                              payload=json.loads(json.dumps(payload, default=str)), latency_ms=latency))

    async def _finish_turn(self, result: TurnResult) -> None:
        call = self.call
        if self.session.language:
            call.language = self.session.language
        if self.session.dialect and self.session.dialect_confidence >= 0.2:
            call.dialect = self.session.dialect
        if result.intent:
            call.intent = call.intent or result.intent
        for action in result.actions:
            if action.get("type") == "transfer":
                call.status, call.transferred_to, call.outcome = "transferred", action.get("label"), "transferred"
                result.transferred = True
            if action.get("type") == "end_call":
                result.ended = True
        if self.workflow_mode and self.session.workflow_state:
            st = self.session.workflow_state
            wx = await self.db.scalar(select(WorkflowExecution).where(WorkflowExecution.call_id == call.id))
            if wx:
                wx.status, wx.current_node = st.get("status", "running"), st.get("current")
                wx.path, wx.variables = list(st.get("path", [])), _public_vars(st.get("variables", {}))
            if st.get("status") in ("completed", "transferred", "failed"):
                result.ended = result.ended or st.get("status") != "transferred"
        metrics = dict(call.metrics or {})
        if "turn_total" in result.latency_ms:
            n = metrics.get("turns", 0)
            avg = metrics.get("avg_turn_latency_ms", 0.0)
            metrics["avg_turn_latency_ms"] = round((avg * n + result.latency_ms["turn_total"]) / (n + 1), 1)
            metrics["turns"] = n + 1
        call.metrics = metrics
        if result.replies:
            self._event("agent_reply", {"replies": result.replies, "latency_ms": result.latency_ms},
                        latency=result.latency_ms.get("turn_total"))
        if result.ended or result.transferred:
            await self.end("agent_ended" if result.ended else "transferred")
        else:
            await self._save()

    async def _save(self) -> None:
        self.conversation.state = json.loads(json.dumps(asdict(self.session), default=str))
        self.conversation.workflow_state = self.session.workflow_state
        await self.db.flush()


def _public_vars(variables: dict[str, Any]) -> dict[str, Any]:
    """Compact view of workflow variables for the debugger (no huge record lists)."""
    out: dict[str, Any] = {}
    for k, v in variables.items():
        if isinstance(v, dict) and "records" in v:
            out[k] = {"status": v.get("status"), "count": v.get("count"), "error": v.get("error")}
        elif isinstance(v, dict) and "record" in v and "value" in v:
            out[k] = {"value": v.get("value"), "label": v.get("label")}
        elif isinstance(v, dict) and "results" in v:
            out[k] = {"found": v.get("found"), "answer": v.get("answer")}
        else:
            out[k] = v
    return out


def _to_hist(m: ChatMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [{"id": t.id, "name": t.name, "arguments": t.arguments} for t in m.tool_calls]
    if m.tool_call_id:
        d["tool_call_id"], d["name"] = m.tool_call_id, m.name
    return d


def _from_hist(d: dict[str, Any]) -> ChatMessage:
    calls = [ToolCall(id=t["id"], name=t["name"], arguments=t["arguments"],
                      arguments_json=json.dumps(t["arguments"], ensure_ascii=False)) for t in d.get("tool_calls") or []]
    return ChatMessage(d["role"], d.get("content") or "", tool_calls=calls or None, tool_call_id=d.get("tool_call_id"),
                       name=d.get("name"))
