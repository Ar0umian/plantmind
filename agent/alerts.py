"""Turns deterministic evidence into operator alerts (rule-based for now).

Evidence that starts while an alert is still open and recent is merged into that
alert (one incident, one alert). Severity here is a deterministic FLOOR; later
steps add model-written explanations and hypotheses but never lower it.
"""
import re
import time
from typing import Dict, List, Optional

from core.contracts import Alert, Evidence, Severity, max_severity

KIND_SEVERITY = {
    "interlock_violation": Severity.high,
    "physical_inconsistency": Severity.high,
    "command_anomaly": Severity.medium,
    "stale_value": Severity.medium,
}
KIND_PRIORITY = ["interlock_violation", "command_anomaly", "physical_inconsistency", "stale_value"]
DECISIONS = ("approved", "rejected", "deferred")


def _title(evidence: List[Evidence]) -> str:
    for kind in KIND_PRIORITY:
        match = next((e for e in evidence if e.kind == kind), None)
        if match is None:
            continue
        if kind == "interlock_violation":
            il = re.match(r"^(IL-\d+)", match.summary)
            base = f"Protective interlock did not act ({il.group(1)})" if il else \
                "Protective interlock did not act"
        elif kind == "command_anomaly":
            base = "Unexpected pump command refused by interlocks"
        elif kind == "physical_inconsistency":
            base = "Readings inconsistent with physical behaviour"
        else:
            base = "Sensor reading frozen"
        extra = len(evidence) - 1
        return base + (f" (+{extra} more finding{'s' if extra > 1 else ''})" if extra > 0 else "")
    return "Anomaly detected"


class AlertManager:
    def __init__(self, merge_window_frames: int = 120):
        self.merge_window_frames = merge_window_frames
        self._alerts: List[Alert] = []
        self._last_frame: Dict[str, int] = {}
        self._counter = 0
        self.decisions: List[dict] = []

    def reset(self) -> None:
        self._alerts.clear()
        self._last_frame.clear()
        self._counter = 0
        self.decisions.clear()

    @property
    def alerts(self) -> List[Alert]:
        """Newest first."""
        return list(reversed(self._alerts))

    def get(self, alert_id: str) -> Optional[Alert]:
        return next((a for a in self._alerts if a.id == alert_id), None)

    def _open_recent(self, frame_no: int) -> Optional[Alert]:
        for alert in reversed(self._alerts):
            if alert.status == "open" and frame_no - self._last_frame[alert.id] <= self.merge_window_frames:
                return alert
        return None

    def ingest(self, new_evidence: List[Evidence], frame_no: int, ts: float) -> List[Alert]:
        """Add evidence that just started; returns the alerts created or updated."""
        if not new_evidence:
            return []
        alert = self._open_recent(frame_no)
        if alert is None:
            self._counter += 1
            alert = Alert(id=f"A-{self._counter:04d}", ts=ts, severity=Severity.info,
                          title="", evidence=[])
            self._alerts.append(alert)
        alert.evidence.extend(new_evidence)
        alert.severity = max_severity(*[KIND_SEVERITY[e.kind] for e in alert.evidence])
        alert.title = _title(alert.evidence)
        self._last_frame[alert.id] = frame_no
        return [alert]

    def decide(self, alert_id: str, decision: str) -> Alert:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        alert = self.get(alert_id)
        if alert is None:
            raise KeyError(alert_id)
        alert.status = decision
        self.decisions.append({"ts": time.time(), "alert_id": alert_id, "decision": decision})
        return alert
