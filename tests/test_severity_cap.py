import os

os.environ["MOCK_LLM"] = "1"

from agent.analysis import AnalysisResult, apply_result
from core.contracts import Alert, Evidence, Severity


def _alert(kind, severity):
    ev = Evidence(id="EV-0001", kind=kind, summary="s", tags=[], ts=1.0)
    return Alert(id="A-0001", ts=1.0, severity=severity, title="t", evidence=[ev])


def _result(suggested):
    return AnalysisResult(triage=None, hypotheses=[], explanation="x", actions=[], tier_used="nano",
                          suggested_severity=suggested)


def test_model_can_raise_severity_by_one_level_only():
    alert = _alert("command_anomaly", Severity.medium)          # rule-based floor: medium
    apply_result(alert, _result(Severity.critical))
    assert alert.severity == Severity.high                      # capped: medium + one level


def test_model_can_raise_a_high_floor_to_critical():
    alert = _alert("interlock_violation", Severity.high)
    apply_result(alert, _result(Severity.critical))
    assert alert.severity == Severity.critical


def test_cap_is_not_compounded_when_the_result_is_applied_twice():
    alert = _alert("command_anomaly", Severity.medium)
    apply_result(alert, _result(Severity.critical))
    apply_result(alert, _result(Severity.critical))
    assert alert.severity == Severity.high


def test_the_floor_is_never_lowered():
    alert = _alert("interlock_violation", Severity.high)
    apply_result(alert, _result(Severity.info))
    assert alert.severity == Severity.high
    apply_result(alert, _result(None))
    assert alert.severity == Severity.high
