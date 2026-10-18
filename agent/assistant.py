"""Operator assistant (FR-OPS-03): grounded questions and answers about the plant.

Advisory only (NFR-SAF-01): requests that ask the system to act on equipment are refused
by a deterministic rule BEFORE any model is called. Answers are built from the knowledge
map and live state; cited sources are validated against IDs that really exist.
"""
import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from agent.context import summarize_frames, summarize_map
from core.contracts import Alert, Evidence, KnowledgeMap, TelemetryFrame
from core.llm_client import LLMClient, LLMError
from knowledge.change_guard import GuardResult

MAX_QUESTION = 500
MAX_HISTORY = 6

COMMAND_RE = re.compile(
    r"^\s*(?:(?:please|pls)\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(start|stop|shut\s*down|shutdown|turn\s+(?:on|off)|restart|open|close|set|override|bypass|"
    r"disable|enable|reset|trip|switch)\b", re.IGNORECASE)

BLOCK_MESSAGE = (
    "PlantMind is an advisory system: it never sends commands to equipment, so I cannot start, stop, "
    "override or bypass anything. I can explain what the plant is doing, why an alert fired, or what to "
    "check first. Any action on the equipment is a human decision made through your site procedures.")

UNAVAILABLE_MESSAGE = ("The assistant is unavailable right now. The alerts, evidence and Change Guard "
                       "results on screen are still current.")


class AssistantAnswer(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list)


class AssistantReply(BaseModel):
    answer: str
    sources: List[str] = Field(default_factory=list)
    mode: Literal["mock", "live", "unavailable", "blocked"]


@dataclass
class AssistantContext:
    frame: Optional[TelemetryFrame]
    alerts: List[Alert] = field(default_factory=list)          # newest first
    evidence: List[Evidence] = field(default_factory=list)     # currently active
    guard: Optional[GuardResult] = None


def is_command_request(text: str) -> bool:
    """True when the user asks the system to act on equipment (not a question about the past)."""
    return COMMAND_RE.match(text) is not None


SYSTEM = (
    "You are PlantMind's operator assistant for a small water treatment plant. Answer the operator's "
    "question using ONLY the context provided (approved PLC logic, live values, rule-based evidence, "
    "alerts, Change Guard result). If the context does not contain the answer, say so plainly.\n"
    "Rules: be short (at most 5 sentences) and use plain language; separate what is certain "
    "(evidence) from what is only likely (model hypotheses); never instruct anyone to send commands to "
    "the equipment, you are advisory only; list in `sources` the IDs you relied on (alert IDs like "
    "A-0001, evidence IDs like EV-0001, interlock IDs like IL-04, finding IDs like F-001, tags like "
    "AT-201). Never invent IDs.")


# ------------------------------------------------------------------ helpers
def _cond_text(il) -> str:
    joiner = " OR " if il.combinator == "any" else " AND "
    return joiner.join(f"{c.tag} is {'on' if c.value else 'off'}" if isinstance(c.value, bool)
                       else f"{c.tag} {c.op} {c.value}" for c in il.conditions)


def _values_text(frame: Optional[TelemetryFrame], kmap: KnowledgeMap, tags: List[str]) -> str:
    if frame is None:
        return "No telemetry has arrived yet."
    units = {e.tag: (e.name, e.unit or "") for e in kmap.equipment}
    parts = []
    for tag in tags:
        if tag in frame.values:
            name, unit = units.get(tag, (tag, ""))
            parts.append(f"{name} {tag} = {frame.values[tag]:.2f} {unit}".strip())
        elif tag in frame.status:
            name = units.get(tag, (tag, ""))[0]
            parts.append(f"{name} {tag} is {'running' if frame.status[tag] else 'stopped'}"
                         f"{' (a start command is being refused)' if frame.commands.get(tag) and not frame.status[tag] else ''}")
    return "; ".join(parts) or "I have no value for that."


def _context_text(kmap: KnowledgeMap, ctx: AssistantContext) -> str:
    lines = [summarize_map(kmap), "", "Live state:"]
    if ctx.frame is not None:
        lines.append(summarize_frames([ctx.frame]))
    lines.append("Active evidence:")
    lines += [f"- {e.id} [{e.kind}]: {e.summary}" for e in ctx.evidence] or ["- none"]
    lines.append("Alerts (newest first):")
    for a in ctx.alerts[:3]:
        top = f" | top cause: {a.hypotheses[0].label} ({round(a.hypotheses[0].confidence * 100)}%)" if a.hypotheses else ""
        lines.append(f"- {a.id} [{a.severity.value}, {a.status}] {a.title}{top}")
        if a.operator_explanation:
            lines.append(f"  explanation: {a.operator_explanation[:300]}")
    if not ctx.alerts:
        lines.append("- none")
    if ctx.guard is None or not ctx.guard.report.findings:
        lines.append("Change Guard: the program running on the PLC matches the approved baseline.")
    else:
        lines.append("Change Guard: the running program DIFFERS from the approved baseline:")
        lines += [f"- {f.id} [{f.final_severity().value}] {f.summary}" for f in ctx.guard.report.findings]
    return "\n".join(lines)


def _known_ids(kmap: KnowledgeMap, ctx: AssistantContext) -> set:
    ids = {e.tag for e in kmap.equipment} | {i.id for i in kmap.interlocks} | {a.id for a in kmap.alarms}
    for alert in ctx.alerts:
        ids.add(alert.id)
        ids |= {e.id for e in alert.evidence}
    ids |= {e.id for e in ctx.evidence}
    if ctx.guard is not None:
        ids |= {f.id for f in ctx.guard.report.findings}
    return ids


# --------------------------------------------------------------- offline mock
def mock_answer(question: str, ctx: AssistantContext, kmap: KnowledgeMap) -> AssistantAnswer:
    """Deterministic stand-in for the model (offline demo and tests)."""
    q = question.lower()
    tag = "[MOCK MODEL] "
    alerts = ctx.alerts
    il_ids = [m.upper() for m in re.findall(r"\bil-\d+\b", q)]

    if il_ids or "interlock" in q:
        chosen = [i for i in kmap.interlocks if not il_ids or i.id in il_ids]
        if not chosen:
            return AssistantAnswer(answer=tag + "I do not know that interlock.", sources=[])
        text = " ".join(f"{i.id} trips {i.target} when {_cond_text(i)}. {i.purpose}".strip() for i in chosen)
        return AssistantAnswer(answer=tag + text, sources=[i.id for i in chosen])

    pump_tags = [t.upper() for t in re.findall(r"\bp-\d{3}\b", q)]
    if pump_tags and any(w in q for w in ("stop", "trip", "shut", "protect", "what stops")):
        pump = pump_tags[0]
        reasons = [i for i in kmap.interlocks if i.target == pump]
        rules = [r.description.split(" (control rule")[0] for r in kmap.relations
                 if r.target == pump and "auto-stops" in r.description]
        if not reasons and not rules:
            return AssistantAnswer(answer=tag + f"I find nothing in the approved program that stops {pump}.",
                                   sources=[pump])
        parts = [f"{i.id}: when {_cond_text(i)}" for i in reasons] + [f"automatic control: {t}" for t in rules]
        return AssistantAnswer(answer=tag + f"{pump} is stopped by " + "; ".join(parts) + ".",
                               sources=[pump] + [i.id for i in reasons])

    if any(w in q for w in ("program", "change guard", "approved", "tamper", "plc logic", "modified")):
        if ctx.guard is None or not ctx.guard.report.findings:
            return AssistantAnswer(answer=tag + "The program running on the PLC matches the approved baseline.", sources=[])
        g = ctx.guard.report
        return AssistantAnswer(
            answer=tag + f"The running program DIFFERS from the approved baseline ({len(g.findings)} finding(s), "
                    f"overall {g.overall_severity.value}). First finding: {g.findings[0].summary}.",
            sources=[f.id for f in g.findings])

    if any(w in q for w in ("check", "first", "should i", "what now", "recommend", "next step", "do now")):
        if alerts and alerts[0].recommended_actions:
            steps = " ".join(f"{n}. {s}" for n, s in enumerate(alerts[0].recommended_actions[:3], start=1))
            return AssistantAnswer(answer=tag + f"For alert {alerts[0].id}, suggested checks (a human decides): {steps}",
                                   sources=[alerts[0].id])
        return AssistantAnswer(answer=tag + "There is no open alert, so nothing needs checking right now.", sources=[])

    if any(w in q for w in ("why", "alert", "happen", "going on", "wrong", "explain", "cause", "problem")):
        if not alerts:
            return AssistantAnswer(answer=tag + "No alerts are open; the plant behaves as the approved PLC logic expects.",
                                   sources=[])
        a = alerts[0]
        text = f"Alert {a.id} ({a.severity.value}, {a.status}): {a.title}."
        if a.evidence:
            text += f" Certain: {a.evidence[0].summary}"
        if a.hypotheses:
            text += f" Most likely cause: {a.hypotheses[0].label.replace('_', ' ')} ({round(a.hypotheses[0].confidence * 100)}%)."
        return AssistantAnswer(answer=tag + text,
                               sources=[a.id] + [e.id for e in a.evidence[:2]])

    specific = {"chlorine": ["AT-201"], "flow": ["FT-101"], "pressure": ["PT-301"]}
    general = {"level": ["LT-101", "LT-301"], "tank": ["LT-101", "LT-301"],
               "pump": ["P-101", "P-201", "P-301"], "status": ["P-101", "P-201", "P-301"]}
    tags = [t.upper() for t in re.findall(r"\b(?:lt|at|ft|pt|p)-\d{3}\b", q)]
    for word, mapped in specific.items():
        if word in q:
            tags += [t for t in mapped if t not in tags]
    if not tags:                                   # "chlorine level" must not also list the tank levels
        for word, mapped in general.items():
            if word in q:
                tags += [t for t in mapped if t not in tags]
    if tags or any(w in q for w in ("value", "reading", "now", "current")):
        tags = tags or ["LT-101", "LT-301", "AT-201", "FT-101", "PT-301"]
        return AssistantAnswer(answer=tag + _values_text(ctx.frame, kmap, tags), sources=tags)

    return AssistantAnswer(
        answer=tag + "I can explain the current alert, what a specific interlock does (for example IL-04), "
                     "whether the PLC program matches the approved one, current values, and what to check first.",
        sources=[])


# ------------------------------------------------------------------- assistant
class OperatorAssistant:
    def __init__(self, llm: LLMClient, kmap: KnowledgeMap):
        self.llm = llm
        self.kmap = kmap

    def ask(self, question: str, ctx: AssistantContext, history: Optional[List[dict]] = None) -> AssistantReply:
        text = " ".join(question.split())[:MAX_QUESTION]
        if not text:
            return AssistantReply(answer="Ask me about the current alert, an interlock, or the plant state.",
                                  sources=[], mode="blocked")
        if is_command_request(text):
            return AssistantReply(answer=BLOCK_MESSAGE, sources=[], mode="blocked")

        turns = []
        for turn in (history or [])[-MAX_HISTORY:]:
            role = "Operator" if turn.get("role") == "user" else "Assistant"
            turns.append(f"{role}: {' '.join(str(turn.get('text', '')).split())[:MAX_QUESTION]}")
        user = (f"{_context_text(self.kmap, ctx)}\n\n"
                + (("Conversation so far:\n" + "\n".join(turns) + "\n\n") if turns else "")
                + f"Operator question: {text}")
        try:
            out = self.llm.generate_json("nano", SYSTEM, user, AssistantAnswer,
                                         mock=lambda: mock_answer(text, ctx, self.kmap))
        except LLMError:
            return AssistantReply(answer=UNAVAILABLE_MESSAGE, sources=[], mode="unavailable")
        known = _known_ids(self.kmap, ctx)
        sources = [s for s in dict.fromkeys(out.sources) if s in known]
        answer = " ".join(out.answer.split())[:1500] or "I could not produce an answer from the available context."
        return AssistantReply(answer=answer, sources=sources, mode="mock" if self.llm.is_mock else "live")
