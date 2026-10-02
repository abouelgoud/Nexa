"""Deterministic workflow engine.

Business logic lives in the graph, not in prompts. The engine only consults the
LLM (through ``WorkflowDeps``) as an optional fallback to understand free-form
caller input; confirmations, branching and tool execution are rule-based.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from nexa.nlp.arabic import (
    matching_key,
    normalize_phone,
    normalize_text,
    similarity,
    strip_definite_article,
    tokens,
)
from nexa.nlp.datetime_norm import extract_date, extract_time
from nexa.nlp.intents import classify_yes_no, keyword_intent
from nexa.schemas.workflow import WorkflowEdgeDef, WorkflowGraph, WorkflowNodeDef
from nexa.tools.templating import drop_empty, localized, render, resolve_path
from nexa.workflow.conditions import ConditionError, evaluate

MAX_STEPS = 60

# Only unambiguous ordinal forms: "ثاني" alone also means "other" ("شي ثاني" = something else).
ORDINALS = {
    0: ["الاول", "الأول", "اول واحد", "أول واحد", "first", "the first one", "1"],
    1: ["الثاني", "التاني", "second", "the second one", "2"],
    2: ["الثالث", "التالت", "third", "the third one", "3"],
    3: ["الرابع", "fourth", "4"],
}
LAST = ["الاخير", "الأخير", "اخر واحد", "last"]
NO_PREFERENCE = ["اي واحد", "أي واحد", "اي احد", "ما يفرق", "مايفرق", "مو مهم", "مش مهم", "any", "anyone",
                 "doesn't matter", "no preference", "اي دكتور", "أي دكتور", "اي طبيب", "أي طبيب", "اللي متاح", "الي متاح"]

RETRY_PREFIX = {"ar": "عذراً، ما فهمت عليك. ", "en": "Sorry, I didn't catch that. "}
YES_NO_RETRY = {"ar": "ممكن تجاوبني بنعم أو لا؟", "en": "Could you answer yes or no?"}


class WorkflowDeps(Protocol):
    async def run_tool(self, name: str, args: dict[str, Any], confirmed: bool) -> Any: ...
    async def search_knowledge(self, query: str) -> dict[str, Any]: ...
    async def classify_intent(self, text: str, intents: dict[str, list[str]]) -> str | None: ...
    async def choose_option(self, text: str, labels: list[str]) -> int | None: ...


@dataclass
class TurnOutput:
    utterances: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)


def new_state(variables: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"current": None, "status": "new", "variables": dict(variables or {}), "path": [], "attempts": {},
            "confirmations": {}, "visits": {}, "entered": None}


class WorkflowEngine:
    def __init__(self, graph: WorkflowGraph, deps: WorkflowDeps, language: str = "ar", now: datetime | None = None):
        self.graph = graph
        self.deps = deps
        self.language = language
        self.now = now or datetime.now()

    # --- public API -------------------------------------------------------------
    async def start(self, state: dict[str, Any]) -> TurnOutput:
        out = TurnOutput()
        start = next(n for n in self.graph.nodes if n.type == "start")
        state.update(current=start.id, status="running", entered=None)
        await self._run(state, out, None)
        return out

    async def handle_input(self, state: dict[str, Any], text: str) -> TurnOutput:
        out = TurnOutput()
        if state.get("status") != "waiting":
            return out
        state["status"] = "running"
        state["variables"]["last_input"] = text
        await self._run(state, out, text)
        return out

    # --- loop -------------------------------------------------------------------------
    async def _run(self, state: dict[str, Any], out: TurnOutput, user_input: str | None) -> None:
        pending_input = user_input
        for _ in range(MAX_STEPS):
            if state["status"] != "running":
                return
            node = self.graph.node(state["current"])
            if state.get("entered") != node.id:
                state["entered"] = node.id
                state["visits"][node.id] = state["visits"].get(node.id, 0) + 1
                state["path"].append(node.id)
                out.events.append({"type": "workflow_node", "node": node.id, "node_type": node.type,
                                   "label": node.label})
            handler = getattr(self, f"_node_{node.type}")
            # The caller's input is consumed by the node that was waiting for it, and only by that node.
            result = await handler(node, state, out, pending_input)
            pending_input = None
            if result == "wait":
                state["status"] = "waiting"
                return
            if result in ("completed", "transferred"):
                state["status"] = result
                return
            edge = result if isinstance(result, WorkflowEdgeDef) else self._edge(node, result)
            if edge is None:
                out.events.append({"type": "workflow_dead_end", "node": node.id, "handle": result})
                state["status"] = "completed"
                return
            state["current"] = edge.target
            state["entered"] = None
        state["status"] = "failed"
        out.events.append({"type": "workflow_error", "error": "Too many steps without waiting for the caller"})

    def _edge(self, node: WorkflowNodeDef, handle: str) -> WorkflowEdgeDef | None:
        edges = self.graph.outgoing(node.id)
        for e in edges:
            if e.handle == handle:
                return e
        for e in edges:
            if e.handle == "default":
                return e
        return None

    def _text(self, cfg: dict[str, Any], key: str, state: dict[str, Any]) -> str:
        raw = cfg.get(f"{key}_en") if self.language == "en" and cfg.get(f"{key}_en") else cfg.get(key, "")
        return str(render(raw or "", state["variables"], self.language) or "")

    def _say(self, out: TurnOutput, text: str) -> None:
        if text.strip():
            out.utterances.append(text.strip())

    # --- node handlers -------------------------------------------------------------
    async def _node_start(self, node, state, out, _input):
        return "default"

    async def _node_say(self, node, state, out, _input):
        self._say(out, self._text(node.config, "text", state))
        return "default"

    async def _node_wait(self, node, state, out, _input):
        self._say(out, self._text(node.config, "text", state))
        out.actions.append({"type": "pause", "seconds": float(node.config.get("seconds", 1))})
        return "default"

    async def _node_end(self, node, state, out, _input):
        self._say(out, self._text(node.config, "text", state))
        out.actions.append({"type": "end_call"})
        return "completed"

    async def _node_ask(self, node, state, out, user_input):
        cfg = node.config
        if user_input is None:
            key = "revisit_question" if state["visits"].get(node.id, 0) > 1 and cfg.get("revisit_question") else "question"
            self._say(out, self._text(cfg, key, state))
            return "wait"
        var = cfg.get("variable") or node.id
        state["variables"][var] = normalize_text(user_input)
        intents: dict[str, list[str]] = cfg.get("intents") or {}
        if not intents:
            return "default"
        intent = await self.deps.classify_intent(user_input, intents)
        state["variables"]["intent"] = intent
        out.events.append({"type": "intent", "node": node.id, "intent": intent})
        handles = {e.handle for e in self.graph.outgoing(node.id)}
        return intent if intent in handles else "default"

    async def _node_condition(self, node, state, out, _input):
        edges = self.graph.outgoing(node.id)
        fallback = None
        for e in edges:
            cond = (e.condition or "").strip()
            if cond in ("", "else") or e.handle == "else":
                fallback = fallback or e
                continue
            try:
                if evaluate(cond, state["variables"]):
                    return e
            except ConditionError as exc:
                out.events.append({"type": "workflow_error", "node": node.id, "error": str(exc)})
        return fallback or "default"

    async def _node_tool(self, node, state, out, _input):
        cfg = node.config
        args = drop_empty(render(cfg.get("arguments") or {}, state["variables"], self.language))
        confirmed = False
        if cfg.get("confirmed_by"):
            confirmed = bool(state["confirmations"].pop(cfg["confirmed_by"], False))
        result = await self.deps.run_tool(cfg["tool"], args, confirmed)
        out.tool_results.append(result)
        data = dict(result.data or {})
        data.update({"status": result.status, "error": result.error})
        state["variables"][cfg.get("result_variable") or node.id] = data
        if result.action:
            out.actions.append(result.action)
        return "success" if result.ok else "error"

    async def _node_knowledge_search(self, node, state, out, _input):
        cfg = node.config
        query = str(render(cfg.get("query", "{{last_input}}"), state["variables"], self.language) or "")
        res = await self.deps.search_knowledge(query)
        state["variables"][cfg.get("result_variable") or "knowledge"] = res
        out.events.append({"type": "knowledge", "query": query, "found": res.get("found", False),
                           "sources": [r.get("document_title") for r in res.get("results", [])]})
        return "found" if res.get("found") else "not_found"

    async def _node_transfer(self, node, state, out, _input):
        cfg = node.config
        result = await self.deps.run_tool("transfer_call", drop_empty(
            {"reason": cfg.get("reason") or node.label or "workflow transfer", "department": cfg.get("target")}), True)
        out.tool_results.append(result)
        if result.ok:
            self._say(out, self._text(cfg, "text", state))
            out.actions.append(result.action)
            return "transferred"
        self._say(out, result.error or "")
        return "default" if self.graph.outgoing(node.id) else "completed"

    async def _node_confirm(self, node, state, out, user_input):
        if user_input is None:
            self._say(out, self._text(node.config, "text", state))
            return "wait"
        answer = classify_yes_no(user_input)
        out.events.append({"type": "confirmation", "node": node.id, "answer": answer})
        if answer is None:
            attempts = state["attempts"].get(node.id, 0) + 1
            state["attempts"][node.id] = attempts
            if attempts >= int(node.config.get("max_attempts", 2)):
                state["attempts"][node.id] = 0
                state["confirmations"][node.id] = False
                return "no"
            self._say(out, YES_NO_RETRY[self.language if self.language in YES_NO_RETRY else "ar"])
            return "wait"
        state["attempts"][node.id] = 0
        state["confirmations"][node.id] = answer == "yes"
        return answer

    async def _node_collect(self, node, state, out, user_input):
        cfg = node.config
        var = cfg.get("variable") or node.id
        first_visit = state["visits"].get(node.id, 0) <= 1
        if user_input is None:
            options = self._options(cfg, state)
            if cfg.get("type") == "choice" and options is not None and not options:
                return "failed"
            if cfg.get("type") == "choice" and cfg.get("auto_select_single") and options and len(options) == 1:
                state["variables"][var] = self._choice_value(cfg, options[0])
                return "default"
            if first_visit and cfg.get("prefill_from"):
                source = resolve_path(state["variables"], cfg["prefill_from"])
                if source:
                    value = await self._extract(cfg, state, str(source), prefill=True)
                    if value is not None:
                        state["variables"][var] = value
                        out.events.append({"type": "collected", "variable": var, "prefilled": True})
                        return "default"
            state["variables"].pop(var, None)
            self._say(out, self._text(cfg, "prompt", state))
            return "wait"
        value = await self._extract(cfg, state, user_input)
        if value is None and cfg.get("optional") and (
            classify_yes_no(user_input) == "no" or any(f" {matching_key(p)} " in f" {matching_key(user_input)} "
                                                       for p in NO_PREFERENCE)):
            state["variables"][var] = {"value": None, "label": None, "record": None}
            out.events.append({"type": "collected", "variable": var, "value": None})
            return "default"
        if value is None:
            attempts = state["attempts"].get(node.id, 0) + 1
            state["attempts"][node.id] = attempts
            if attempts >= int(cfg.get("max_attempts", 2)):
                state["attempts"][node.id] = 0
                if cfg.get("optional"):
                    state["variables"][var] = {"value": None, "label": None, "record": None}
                    return "default"
                return "failed"
            self._say(out, RETRY_PREFIX.get(self.language, "") + self._text(cfg, "prompt", state))
            return "wait"
        state["attempts"][node.id] = 0
        state["variables"][var] = value
        out.events.append({"type": "collected", "variable": var,
                           "value": value.get("value") if isinstance(value, dict) else value})
        return "default"

    # --- extraction --------------------------------------------------------------------
    def _options(self, cfg: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]] | None:
        if not cfg.get("options_from"):
            return None
        options = resolve_path(state["variables"], cfg["options_from"])
        return options if isinstance(options, list) else []

    def _choice_value(self, cfg: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        display = cfg.get("display_field") or (cfg.get("label_fields") or ["label"])[0]
        label = localized(record, display, self.language)
        return {"value": record.get(cfg.get("value_field", "id")), "label": label, "record": record}

    async def _extract(self, cfg: dict[str, Any], state: dict[str, Any], text: str, prefill: bool = False) -> Any:
        kind = cfg.get("type", "text")
        if kind == "phone":
            return normalize_phone(text, cfg.get("country_code", "966"))
        if kind == "date":
            d = extract_date(text, self.now.date())
            return d.isoformat() if d else None
        if kind == "time":
            t, _ = extract_time(text)
            return t.strftime("%H:%M") if t else None
        if kind == "number":
            m = re.search(r"\d+(?:\.\d+)?", normalize_text(text))
            return float(m.group()) if m else None
        if kind == "choice":
            options = self._options(cfg, state) or []
            idx = await self._match_option(cfg, options, text, allow_llm=not prefill)
            return self._choice_value(cfg, options[idx]) if idx is not None else None
        if prefill:
            return None
        value = normalize_text(text)
        return value or None

    async def _match_option(self, cfg: dict[str, Any], options: list[dict[str, Any]], text: str,
                            allow_llm: bool = True) -> int | None:
        if not options:
            return None
        key = f" {matching_key(text)} "
        # 1) date/time matching for slots
        if cfg.get("match") == "datetime":
            idx = self._match_datetime(cfg, options, text)
            if idx is not None:
                return idx
        # 2) ordinals ("the second one")
        if allow_llm:
            for i, words in ORDINALS.items():
                if i < len(options) and any(f" {matching_key(w)} " in key for w in words) and len(tokens(text)) <= 4:
                    return i
            if any(f" {matching_key(w)} " in key for w in LAST):
                return len(options) - 1
        # 3) label / keyword matching
        input_tokens = {strip_definite_article(t) for t in tokens(text)}
        scores: list[float] = []
        for opt in options:
            best = 0.0
            for f in cfg.get("label_fields") or ["label"]:
                value = opt.get(f)
                if not value:
                    continue
                best = max(best, similarity(text, str(value)))
                field_tokens = {strip_definite_article(t) for t in tokens(str(value)) if len(t) >= 3}
                field_tokens -= {"مع", "الساعه", "with", "at", "د", "dr"}
                if field_tokens:
                    hit = sum(1 for ft in field_tokens if any(_token_match(ft, it) for it in input_tokens))
                    if hit:
                        best = max(best, 0.6 + 0.4 * hit / len(field_tokens))
            scores.append(best)
        top = max(scores)
        if top >= 0.6 and scores.count(top) == 1:
            return scores.index(top)
        # 4) optional LLM fallback for free-form answers
        if allow_llm:
            labels = [str(localized(o, (cfg.get("label_fields") or ["label"])[0].rsplit("_", 1)[0], self.language)
                          or o) for o in options]
            choice = await self.deps.choose_option(text, labels)
            if choice is not None and 0 <= choice < len(options):
                return choice
        return None

    def _match_datetime(self, cfg: dict[str, Any], options: list[dict[str, Any]], text: str) -> int | None:
        d = extract_date(text, self.now.date())
        t, ambiguous = extract_time(text)
        if d is None and t is None:
            return None
        date_field, time_field = cfg.get("date_field", "date"), cfg.get("time_field")
        candidates = list(range(len(options)))
        if d is not None:
            candidates = [i for i in candidates if str(options[i].get(date_field, ""))[:10] == d.isoformat()]
        if t is not None:
            def opt_time(o: dict[str, Any]) -> str:
                if time_field and o.get(time_field):
                    return str(o[time_field])[:5]
                raw = str(o.get(date_field, ""))
                return raw[11:16] if len(raw) >= 16 else ""
            wanted = {t.strftime("%H:%M")}
            if ambiguous:
                wanted.add(f"{(t.hour % 12) + 12:02d}:{t.minute:02d}")
            timed = [i for i in candidates if opt_time(options[i]) in wanted]
            if timed:
                candidates = timed
            elif d is None:
                candidates = []
        return candidates[0] if len(candidates) == 1 else None


def _token_match(a: str, b: str) -> bool:
    """Exact match, or one word is a prefix of the other (dentist/dentistry, جلد/جلديه)."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long_.startswith(short)


class KeywordNLU:
    """Default, deterministic NLU used when no LLM is available."""

    async def classify_intent(self, text: str, intents: dict[str, list[str]]) -> str | None:
        return keyword_intent(text, intents)

    async def choose_option(self, text: str, labels: list[str]) -> int | None:
        return None
