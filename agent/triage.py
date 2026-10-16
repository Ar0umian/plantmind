"""Fast triage with the small model (Nano): route an alert, never decide alone.

Deterministic evidence comes first. The model only chooses how much deeper
analysis the alert deserves and may RAISE (never lower) the severity.
"""
from typing import List, Literal

from pydantic import BaseModel

from agent.context import format_evidence, summarize_frames
from core.contracts import Alert, Evidence, KnowledgeMap, Severity, TelemetryFrame
from core.llm_client import LLMClient


class TriageResult(BaseModel):
    escalate_to: Literal["none", "super", "ultra"]
    suggested_severity: Severity
    summary: str


TRIAGE_SYSTEM = (
    "You are the first-line triage assistant of an industrial control system (ICS) safety "
    "monitor at a water treatment plant. You receive deterministic evidence items produced by "
    "rule-based checks. Decide quickly how much deeper analysis the alert needs.\n"
    "Routing: 'none' = a single low-risk finding that needs no deep analysis; 'super' = ordinary "
    "multi-signal analysis; 'ultra' = safety-critical or ambiguous situations. When a protective "
    "interlock did not act, always route to 'ultra'.\n"
    "suggested_severity is one of info, low, medium, high, critical. summary is one plain sentence "
    "(max 200 characters) for a control-room operator. You never issue commands to equipment."
)


def mock_triage(alert: Alert) -> TriageResult:
    kinds = {e.kind for e in alert.evidence}
    if "interlock_violation" in kinds or len(alert.evidence) >= 3:
        route = "ultra"
    elif len(alert.evidence) >= 2 or kinds - {"stale_value"}:
        route = "super"
    else:
        route = "none"
    first = alert.evidence[0].summary if alert.evidence else "no evidence"
    return TriageResult(escalate_to=route, suggested_severity=alert.severity,
                        summary=f"{len(alert.evidence)} finding(s); first: {first}"[:200])


def run_triage(llm: LLMClient, alert: Alert, frames: List[TelemetryFrame],
               extra_context: str = "") -> TriageResult:
    user = (f"Alert {alert.id} (rule-based severity: {alert.severity.value})\n"
            f"Evidence:\n{format_evidence(alert.evidence)}\n\n{summarize_frames(frames)}\n")
    if extra_context:
        user += f"\nAdditional context:\n{extra_context}\n"
    result = llm.generate_json("nano", TRIAGE_SYSTEM, user, TriageResult,
                               mock=lambda: mock_triage(alert))
    return TriageResult(escalate_to=result.escalate_to,
                        suggested_severity=result.suggested_severity,
                        summary=" ".join(result.summary.split())[:300])
