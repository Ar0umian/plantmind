"""Deep analysis (Super/Ultra): ranked hypotheses grounded in evidence IDs.

The model may only cite evidence IDs produced by the deterministic layer.
`validate_output` discards anything else (FR-DET-06).
"""
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field

from agent.context import format_evidence, summarize_frames, summarize_map
from core.contracts import Alert, Hypothesis, KnowledgeMap, TelemetryFrame
from core.llm_client import LLMClient

MAX_HYPOTHESES = 4
MAX_ACTIONS = 5


class ReasonerOutput(BaseModel):
    hypotheses: List[Hypothesis]
    operator_explanation: str
    recommended_actions: List[str] = Field(default_factory=list)


REASONER_SYSTEM = (
    "You are a senior ICS/SCADA safety analyst assisting the operators of a water treatment plant. "
    "A rule-based detector compares live data with the APPROVED PLC program and produced the "
    "evidence items below. Explain what is most likely happening and rank the possible causes.\n\n"
    "Candidate causes (label): sensor_fault, process_upset, spoofing, logic_tampering, command_abuse, unknown.\n"
    "How to tell them apart:\n"
    "- sensor_fault: one instrument misbehaves like hardware does (reading exactly constant, stuck, "
    "noise vanished) while the rest of the plant stays physically consistent.\n"
    "- spoofing: reported values look plausible (they keep natural noise) but contradict physics "
    "visible elsewhere, e.g. a level that stays steady while the pump runs and the flow collapses.\n"
    "- logic_tampering: protective logic did not act although its condition is true, or the PLC "
    "program differs from the approved one.\n"
    "- command_abuse: start commands are issued to pumps whose interlocks refuse them, without an "
    "operator reason.\n"
    "- process_upset: a genuine disturbance visible consistently across several instruments.\n\n"
    "Rules:\n"
    "1. Cite ONLY evidence IDs from the list (like EV-0001) in each hypothesis. Never invent IDs or facts.\n"
    "2. Confidences are your relative belief between 0 and 1 and must sum to at most 1.\n"
    "3. Give at most 4 hypotheses, most likely first.\n"
    "4. operator_explanation: 2 to 4 plain sentences for a control-room operator; say what is "
    "certain (the evidence) and what is only likely (your hypotheses).\n"
    "5. recommended_actions: up to 5 ordered CHECKS for a human to perform (verify locally, compare "
    "against an independent measurement, review access logs). They are suggestions that a human "
    "approves. Never tell anyone to send commands to the equipment yourself."
)


def validate_output(out: ReasonerOutput, alert: Alert) -> Tuple[ReasonerOutput, List[str]]:
    """Keep only claims grounded in this alert's evidence; returns (clean output, notes)."""
    valid = {e.id for e in alert.evidence}
    notes: List[str] = []
    cleaned: List[Hypothesis] = []
    for h in out.hypotheses:
        ids = [i for i in dict.fromkeys(h.evidence_ids) if i in valid]
        dropped = [i for i in h.evidence_ids if i not in valid]
        if dropped:
            notes.append(f"dropped unknown evidence ids {dropped} from hypothesis '{h.label}'")
        if not ids:
            notes.append(f"discarded hypothesis '{h.label}': it cites no valid evidence")
            continue
        cleaned.append(Hypothesis(label=h.label, confidence=min(1.0, max(0.0, h.confidence)),
                                  reasoning=" ".join(h.reasoning.split()), evidence_ids=ids))
    cleaned.sort(key=lambda h: h.confidence, reverse=True)
    cleaned = cleaned[:MAX_HYPOTHESES]
    total = sum(h.confidence for h in cleaned)
    if total > 1.0:
        cleaned = [Hypothesis(label=h.label, confidence=h.confidence / total,
                              reasoning=h.reasoning, evidence_ids=h.evidence_ids) for h in cleaned]
        notes.append("confidences summed above 1 and were normalized")
    if not cleaned:
        cleaned = [Hypothesis(label="unknown", confidence=1.0,
                              reasoning="The model gave no hypothesis grounded in the evidence; "
                                        "the evidence is listed for human review.",
                              evidence_ids=sorted(valid))]
        notes.append("no usable hypothesis: fell back to 'unknown'")
    actions = [" ".join(a.split()) for a in out.recommended_actions if a.strip()][:MAX_ACTIONS]
    return ReasonerOutput(hypotheses=cleaned,
                          operator_explanation=" ".join(out.operator_explanation.split()),
                          recommended_actions=actions), notes


# ------------------------------------------------------------------ offline mock
_MOCK_ACTIONS: Dict[str, List[str]] = {
    "logic_tampering": [
        "Compare the PLC program currently running with the approved baseline (Change Guard).",
        "Test locally whether the protected pump trips at its interlock condition.",
        "Treat the affected system as unprotected until the logic is verified.",
    ],
    "sensor_fault": [
        "Verify the suspect instrument locally against an independent or manual measurement.",
        "Check the instrument power supply, wiring and calibration.",
        "Do not rely on this reading for automatic control until it is verified.",
    ],
    "spoofing": [
        "Cross-check the suspect reading against an independent measurement.",
        "Review recent remote-access and communication logs for that instrument.",
        "Treat the reading as untrusted until it is verified.",
    ],
    "command_abuse": [
        "Identify the source of the start commands (HMI/SCADA session, user, network address).",
        "Review recent remote sessions and write operations to the PLC.",
        "Confirm the interlocks are still healthy.",
    ],
    "process_upset": [
        "Check the process for a genuine disturbance (inflow, demand, source quality).",
        "Compare several instruments to confirm the disturbance is real.",
    ],
    "unknown": ["Review the evidence items manually and verify the instruments locally."],
}


def mock_reasoner(alert: Alert) -> ReasonerOutput:
    """Deterministic stand-in for the model, used offline (MOCK_LLM=1) and in tests."""
    kinds = [e.kind for e in alert.evidence]
    has_stale = "stale_value" in kinds
    score: Dict[str, float] = {}
    cites: Dict[str, List[str]] = {}

    def add(label: str, weight: float, evidence_id: str) -> None:
        score[label] = score.get(label, 0.0) + weight
        cites.setdefault(label, []).append(evidence_id)

    for e in alert.evidence:
        if e.kind == "interlock_violation":
            add("logic_tampering", 3.0, e.id)
            add("sensor_fault", 0.5, e.id)
        elif e.kind == "command_anomaly":
            add("command_abuse", 3.0, e.id)
            add("process_upset", 0.5, e.id)
        elif e.kind == "stale_value":
            add("sensor_fault", 3.0, e.id)
            add("spoofing", 0.5, e.id)
        elif has_stale:
            add("sensor_fault", 1.5, e.id)
        else:
            add("spoofing", 2.0, e.id)
            add("sensor_fault", 1.0, e.id)
            add("process_upset", 0.7, e.id)

    total = sum(score.values()) or 1.0
    ranked = sorted(score.items(), key=lambda kv: kv[1], reverse=True)[:3]
    hypotheses = [Hypothesis(label=label, confidence=round(value / total, 2),
                             reasoning=f"Mock analysis: evidence pattern fits {label.replace('_', ' ')}.",
                             evidence_ids=list(dict.fromkeys(cites[label])))
                  for label, value in ranked]
    top = hypotheses[0].label if hypotheses else "unknown"
    more = len(alert.evidence) - 1
    facts = alert.evidence[0].summary if alert.evidence else "no evidence"
    if more > 0:
        facts += f" ({more} more finding{'s' if more > 1 else ''} support this.)"
    explanation = (f"[MOCK MODEL - offline demo, not a real AI analysis] Certain: {facts} "
                   f"Most likely cause: {top.replace('_', ' ')}.")
    return ReasonerOutput(hypotheses=hypotheses, operator_explanation=explanation,
                          recommended_actions=_MOCK_ACTIONS.get(top, _MOCK_ACTIONS["unknown"]))


def run_reasoner(llm: LLMClient, tier: str, alert: Alert, kmap: KnowledgeMap,
                 frames: List[TelemetryFrame], extra_context: str = "") -> Tuple[ReasonerOutput, List[str]]:
    user = (f"{summarize_map(kmap)}\n\n"
            f"Alert {alert.id} (rule-based severity: {alert.severity.value})\n"
            f"Evidence items (cite these IDs only):\n{format_evidence(alert.evidence)}\n\n"
            f"{summarize_frames(frames)}\n")
    if extra_context:
        user += f"\nAdditional context:\n{extra_context}\n"
    raw = llm.generate_json(tier, REASONER_SYSTEM, user, ReasonerOutput,
                            mock=lambda: mock_reasoner(alert))
    return validate_output(raw, alert)
