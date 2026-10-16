"""Analysis pipeline: triage (Nano) -> optional deep analysis (Super/Ultra) -> validated result.

Cost control (FR-DET-07, NFR-CST-01): an alert is only re-analyzed when its evidence
changed, identical evidence is served from a cache, and deep calls have a per-run budget.
If the model fails, the deterministic alert stays untouched (NFR-REL-01).
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from agent.reasoner import run_reasoner
from agent.triage import TriageResult, run_triage
from core.contracts import (Alert, Hypothesis, KnowledgeMap, Severity, TelemetryFrame,
                            max_severity)
from core.llm_client import LLMClient, LLMError


@dataclass
class AnalysisResult:
    triage: Optional[TriageResult]
    hypotheses: List[Hypothesis]
    explanation: str
    actions: List[str]
    tier_used: str                      # "nano" when no deep call was made
    suggested_severity: Optional[Severity] = None
    available: bool = True              # False when the model could not be used
    notes: List[str] = field(default_factory=list)


class AnalysisPipeline:
    def __init__(self, llm: LLMClient, kmap: KnowledgeMap, max_deep_calls: int = 40,
                 context_provider: Optional[Callable[[Alert], str]] = None):
        self.llm = llm
        self.kmap = kmap
        self.max_deep_calls = max_deep_calls
        self.context_provider = context_provider
        self.stats: Dict[str, int] = {"triage_calls": 0, "deep_calls": 0, "cache_hits": 0,
                                      "skipped": 0, "failures": 0}
        self._seen: Dict[str, Tuple] = {}
        self._cache: Dict[Tuple, AnalysisResult] = {}

    def reset(self) -> None:
        self._seen.clear()
        self._cache.clear()

    @staticmethod
    def _signature(alert: Alert) -> Tuple:
        return tuple((e.id, e.kind, e.summary) for e in alert.evidence)

    def analyze(self, alert: Alert, frames: List[TelemetryFrame]) -> Optional[AnalysisResult]:
        """Returns a result, or None when this exact evidence was already analyzed."""
        signature = self._signature(alert)
        if self._seen.get(alert.id) == signature:
            self.stats["skipped"] += 1
            return None
        self._seen[alert.id] = signature

        cached = self._cache.get(signature)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return cached

        extra = self.context_provider(alert) if self.context_provider else ""
        notes: List[str] = []
        try:
            self.stats["triage_calls"] += 1
            triage = run_triage(self.llm, alert, frames, extra)
        except LLMError as exc:
            self.stats["failures"] += 1
            return AnalysisResult(None, [], "AI analysis is unavailable; the rule-based findings above "
                                  "stand on their own.", [], "nano", available=False,
                                  notes=[f"triage failed: {exc}"])

        if triage.escalate_to == "none":
            result = AnalysisResult(triage, [], triage.summary,
                                    ["Review the finding and verify the instrument locally."],
                                    "nano", triage.suggested_severity)
        elif self.stats["deep_calls"] >= self.max_deep_calls:
            result = AnalysisResult(triage, [], triage.summary, [], "nano", triage.suggested_severity,
                                    notes=["deep-analysis budget reached; triage summary only"])
        else:
            try:
                self.stats["deep_calls"] += 1
                out, notes = run_reasoner(self.llm, triage.escalate_to, alert, self.kmap, frames, extra)
                result = AnalysisResult(triage, out.hypotheses, out.operator_explanation,
                                        out.recommended_actions, triage.escalate_to,
                                        triage.suggested_severity, notes=notes)
            except LLMError as exc:
                self.stats["failures"] += 1
                result = AnalysisResult(triage, [], triage.summary, [], "nano",
                                        triage.suggested_severity, available=False,
                                        notes=[f"deep analysis failed: {exc}"])
        if result.available:
            self._cache[signature] = result
        return result


def apply_result(alert: Alert, result: AnalysisResult) -> None:
    """Write the analysis onto the alert. The rule-based severity is a floor: never lowered."""
    alert.hypotheses = list(result.hypotheses)
    alert.operator_explanation = result.explanation
    alert.recommended_actions = list(result.actions)
    alert.triage_tier = result.tier_used if result.tier_used in ("nano", "super", "ultra") else "nano"
    alert.severity = max_severity(alert.severity, result.suggested_severity)
