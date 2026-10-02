"""System prompt construction. Contains configuration only - never credentials or tool internals."""

from __future__ import annotations

from datetime import datetime

from nexa.schemas.agent_definition import DIALECT_LABELS, AgentDefinition

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_system_prompt(defn: AgentDefinition, now: datetime, caller_language: str | None,
                        caller_dialect: str | None, dialect_confidence: float, is_open: bool) -> str:
    g = defn.general
    lines = [
        f"You are the AI phone agent for {g.business_name or defn.name}. {defn.description}".strip(),
        f"Industry: {g.industry}.",
        f"Current local date/time: {DAY_NAMES[now.weekday()]} {now.strftime('%Y-%m-%d %H:%M')} ({g.timezone}). "
        f"Resolve relative dates such as 'tomorrow', 'next Monday', 'بكرة', 'الاثنين الجاي' from this date. "
        f"Pass dates to actions as YYYY-MM-DD.",
        f"The business is currently {'OPEN' if is_open else 'CLOSED'}.",
    ]
    if g.operating_hours:
        hours = ", ".join(f"{h.day} {h.open}-{h.close}" for h in g.operating_hours)
        lines.append(f"Operating hours: {hours}.")

    langs = {"ar": "Arabic", "en": "English"}
    lb = defn.language_behavior
    if lb.mode == "match_caller":
        lines.append(f"Languages: {', '.join(langs[x] for x in defn.languages)}. Reply in the caller's language.")
    else:
        lines.append(f"Always reply in {langs[lb.primary_language]}.")
    if "ar" in defn.languages:
        if lb.code_switching:
            lines.append("Callers may mix Arabic and English in one sentence (e.g. 'أبغى أحجز appointment'). "
                         "Understand both naturally and answer mainly in Arabic unless they speak mostly English.")
        if lb.response_dialect == "match_caller":
            if caller_dialect and dialect_confidence >= 0.35 and caller_dialect in DIALECT_LABELS:
                lines.append(f"The caller seems to speak {DIALECT_LABELS[caller_dialect][0]} Arabic; reply in a "
                             "natural, polite version of that dialect that any Arab speaker understands.")
            else:
                lines.append("Reply in clear, simple, widely understood Arabic (light Gulf/white dialect).")
        else:
            lines.append(f"When speaking Arabic use {DIALECT_LABELS[lb.response_dialect][0]} Arabic.")
    if caller_language:
        lines.append(f"The caller's last message was mostly in {langs.get(caller_language, caller_language)}.")

    p = defn.personality
    lines.append(f"Tone: {p.tone}. Length: {p.verbosity}.")
    if defn.capabilities:
        lines.append("You can help with: " + ", ".join(c.replace("_", " ") for c in defn.capabilities) + ".")
    rules = [
        "This is a voice call: answer in 1-2 short spoken sentences. No markdown, lists, emojis or URLs.",
        "Ask for one piece of information at a time.",
        "Only use the provided actions to look up or change data. Never guess ids, prices, times or availability.",
        "Never say an action is done (booked, cancelled, changed, sent) unless the action result status is "
        "'succeeded' in this conversation.",
    ]
    if defn.policies.never_invent_information:
        rules.append("Never invent information. For questions about the business use search_knowledge; if it finds "
                     "nothing relevant, say you don't have that information and offer to transfer to staff.")
    if defn.policies.require_confirmation_for_booking:
        rules.append("Before booking, cancelling or changing anything, read the details back and get a clear yes.")
    if defn.handoff.enabled and defn.policies.human_handoff_enabled:
        rules.append("If the caller asks for a human, or you cannot complete their request, use transfer_call.")
    lines.append("Rules:\n- " + "\n- ".join(rules))
    if p.custom_instructions.strip():
        lines.append("Business instructions:\n" + p.custom_instructions.strip())
    return "\n".join(lines)
