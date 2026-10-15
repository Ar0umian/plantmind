"""Shared data contracts for PlantMind.

Both workstreams import from here. Any change to this file must bump
CONTRACT_VERSION and be communicated to both workstreams through Aram.
"""
import hashlib
from enum import Enum
from typing import Dict, List, Literal, Optional, Protocol, Union, runtime_checkable

from pydantic import BaseModel, Field

CONTRACT_VERSION = "0.1.0"

SENSOR_TAGS = ["LT-101", "FT-101", "AT-201", "LT-301", "PT-301"]
PUMP_TAGS = ["P-101", "P-201", "P-301"]
SCENARIOS = ["normal", "sensor_fault", "spoofed_reading", "logic_tamper", "abnormal_command"]


def sha256_text(text: str) -> str:
    """Short stable hash used to identify a PLC program version."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- severity
class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


_SEV_ORDER = {Severity.info: 0, Severity.low: 1, Severity.medium: 2,
              Severity.high: 3, Severity.critical: 4}


def max_severity(*items: Optional[Severity]) -> Severity:
    """Highest severity among the given values (None values are ignored)."""
    present = [s for s in items if s is not None]
    if not present:
        return Severity.info
    return max(present, key=lambda s: _SEV_ORDER[s])


# --------------------------------------------------------------- telemetry
class TelemetryFrame(BaseModel):
    """One snapshot of the plant. Produced by the simulator (A)."""
    ts: float                                   # unix seconds
    tick: int                                   # monotonically increasing
    values: Dict[str, float]                    # analog tags, e.g. LT-101
    status: Dict[str, bool]                     # pump running state, e.g. P-101
    commands: Dict[str, bool] = Field(default_factory=dict)  # commanded pump state
    # Ground-truth label for tests and the demo panel ONLY.
    # Detection code (B) must never read this field.
    scenario: str = "normal"


# ----------------------------------------------------------- knowledge map
class Condition(BaseModel):
    tag: str
    op: Literal["<", "<=", ">", ">=", "==", "!="]
    value: Union[bool, float]


class Interlock(BaseModel):
    id: str                                     # e.g. IL-04
    target: str                                 # equipment that trips, e.g. P-201
    action: Literal["trip"] = "trip"
    conditions: List[Condition]
    combinator: Literal["any", "all"] = "any"   # how conditions combine
    purpose: str = ""                           # plain-language purpose
    source_lines: Optional[List[int]] = None    # lines in the .st file


class Alarm(BaseModel):
    id: str                                     # e.g. AL-01
    tag: str
    op: Literal["<", "<=", ">", ">=", "==", "!="]
    value: float
    message: str = ""


class Equipment(BaseModel):
    tag: str
    name: str
    kind: Literal["sensor", "pump", "tank", "valve", "other"]
    unit: Optional[str] = None


class Relation(BaseModel):
    """Expected physical relation, e.g. LT-101 falls when P-101 runs and inflow is low."""
    source: str
    target: str
    description: str


class KnowledgeMap(BaseModel):
    """Produced by A (map builder), consumed by A and B."""
    contract_version: str = CONTRACT_VERSION
    plant_name: str
    program_hash: str
    equipment: List[Equipment]
    interlocks: List[Interlock]
    alarms: List[Alarm] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)


# ------------------------------------------------------------- change guard
class MitreRef(BaseModel):
    technique_id: str
    name: str


class Finding(BaseModel):
    id: str                                     # e.g. F-001
    kind: Literal["added", "removed", "modified"]
    interlock_id: Optional[str] = None
    summary: str
    rule_severity: Severity                     # set by deterministic rules
    llm_severity: Optional[Severity] = None     # set by the model, may be None
    hazard: str = ""                            # plain-language hazardous scenario
    recommendation: str = ""
    mitre: List[MitreRef] = Field(default_factory=list)

    def final_severity(self) -> Severity:
        """The model can raise severity but never lower the rule-based floor."""
        return max_severity(self.rule_severity, self.llm_severity)


class ChangeReport(BaseModel):
    """Produced by A (change guard), consumed by B (UI, reports)."""
    contract_version: str = CONTRACT_VERSION
    baseline_hash: str
    candidate_hash: str
    findings: List[Finding]
    overall_severity: Severity
    llm_available: bool = True
    decision: Literal["pending", "approved", "rejected", "needs_review"] = "pending"


# ------------------------------------------------------- detection and alerts
class Evidence(BaseModel):
    """Deterministic evidence. The model may only cite these IDs."""
    id: str                                     # e.g. EV-0007
    kind: Literal["interlock_violation", "physical_inconsistency",
                  "command_anomaly", "stale_value"]
    summary: str
    tags: List[str] = Field(default_factory=list)
    ts: float


HypothesisLabel = Literal["sensor_fault", "process_upset", "spoofing",
                          "logic_tampering", "command_abuse", "unknown"]


class Hypothesis(BaseModel):
    label: HypothesisLabel
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence_ids: List[str]


class Alert(BaseModel):
    id: str
    ts: float
    severity: Severity
    title: str
    evidence: List[Evidence]
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    operator_explanation: str = ""
    recommended_actions: List[str] = Field(default_factory=list)
    status: Literal["open", "approved", "rejected", "deferred"] = "open"
    triage_tier: Optional[Literal["nano", "super", "ultra"]] = None


class ReferenceLink(BaseModel):
    title: str
    url: str


class IncidentReport(BaseModel):
    id: str
    alert_id: str
    created_ts: float
    timeline: List[str]
    evidence: List[Evidence]
    hypotheses: List[Hypothesis]
    actions: List[str]
    mitre: List[MitreRef] = Field(default_factory=list)
    references: List[ReferenceLink] = Field(default_factory=list)
    markdown: str = ""


# ------------------------------------------------------------ plant runner
@runtime_checkable
class PlantRunner(Protocol):
    """Interface A's simulator runner must implement; B's routers call it."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def list_scenarios(self) -> List[str]: ...
    def start_scenario(self, name: str) -> None: ...
    def stop_scenario(self) -> None: ...
    def latest_frame(self) -> Optional[TelemetryFrame]: ...
    def recent_frames(self, n: int = 60) -> List[TelemetryFrame]: ...
