import os

os.environ["MOCK_LLM"] = "1"

from agent.alerts import AlertManager
from agent.analysis import AnalysisPipeline, apply_result
from agent.detector import Detector
from agent.engine import load_approved_map
from agent.reasoner import ReasonerOutput, validate_output
from agent.triage import mock_triage
from core.contracts import Alert, Evidence, Hypothesis, Severity
from core.llm_client import LLMClient, LLMError
from plant.simulator.runner import SimulatorRunner


def _alert_for(scenario, ticks):
    """Builds a real alert the same way the engine does (detector -> alert manager)."""
    kmap = load_approved_map()
    runner = SimulatorRunner(interval_s=0.0, seed=7)
    detector, manager = Detector(kmap), AlertManager()
    if scenario != "normal":
        runner.start_scenario(scenario)
    frames = []
    for n in range(1, ticks + 1):
        frame = runner.step_once()
        frames.append(frame)
        manager.ingest(detector.process(frame), n, frame.ts)
    alerts = manager.alerts
    return (alerts[0] if alerts else None), frames[-60:], kmap


def _ev(i, kind="stale_value"):
    return Evidence(id=f"EV-{i:04d}", kind=kind, summary=f"finding {i}", tags=["AT-201"], ts=float(i))


def _alert(*evidence):
    return Alert(id="A-0001", ts=1.0, severity=Severity.medium, title="t", evidence=list(evidence))


def _hyp(label, confidence, ids):
    return Hypothesis(label=label, confidence=confidence, reasoning="because  of\nthis", evidence_ids=ids)


def test_validate_drops_unknown_evidence_ids():
    alert = _alert(_ev(1), _ev(2))
    out = ReasonerOutput(hypotheses=[_hyp("sensor_fault", 0.6, ["EV-0001", "EV-9999"])],
                         operator_explanation="x", recommended_actions=["a"])
    clean, notes = validate_output(out, alert)
    assert clean.hypotheses[0].evidence_ids == ["EV-0001"]
    assert any("EV-9999" in n for n in notes)
    assert clean.hypotheses[0].reasoning == "because of this"      # whitespace normalized


def test_validate_discards_ungrounded_hypotheses_and_falls_back():
    alert = _alert(_ev(1), _ev(2))
    out = ReasonerOutput(hypotheses=[_hyp("spoofing", 0.9, ["EV-7777"])],
                         operator_explanation="x", recommended_actions=[])
    clean, notes = validate_output(out, alert)
    assert [h.label for h in clean.hypotheses] == ["unknown"]
    assert clean.hypotheses[0].evidence_ids == ["EV-0001", "EV-0002"]
    assert any("fell back" in n for n in notes)


def test_validate_normalizes_confidences_sorts_and_caps():
    alert = _alert(_ev(1))
    labels = ["sensor_fault", "spoofing", "process_upset", "logic_tampering", "command_abuse"]
    out = ReasonerOutput(
        hypotheses=[_hyp(label, 0.5, ["EV-0001"]) for label in labels],
        operator_explanation="x", recommended_actions=["a"] * 9)
    clean, notes = validate_output(out, alert)
    assert len(clean.hypotheses) == 4 and len(clean.recommended_actions) == 5
    assert abs(sum(h.confidence for h in clean.hypotheses) - 1.0) < 1e-9
    assert any("normalized" in n for n in notes)
    out2 = ReasonerOutput(hypotheses=[_hyp("spoofing", 0.2, ["EV-0001"]), _hyp("sensor_fault", 0.7, ["EV-0001"])],
                          operator_explanation="x", recommended_actions=[])
    assert validate_output(out2, alert)[0].hypotheses[0].label == "sensor_fault"


def test_mock_triage_routes_by_risk():
    assert mock_triage(_alert(_ev(1))).escalate_to == "none"
    assert mock_triage(_alert(_ev(1), _ev(2))).escalate_to == "super"
    assert mock_triage(_alert(_ev(1, "interlock_violation"))).escalate_to == "ultra"


def _analyze(scenario, ticks):
    alert, frames, kmap = _alert_for(scenario, ticks)
    pipeline = AnalysisPipeline(LLMClient(), kmap)
    result = pipeline.analyze(alert, frames)
    return alert, result, pipeline


def test_each_scenario_gets_the_expected_top_hypothesis_in_mock_mode():
    expected = {"logic_tamper": "logic_tampering", "spoofed_reading": "spoofing",
                "sensor_fault": "sensor_fault", "abnormal_command": "command_abuse"}
    ticks = {"logic_tamper": 120, "spoofed_reading": 140, "sensor_fault": 60, "abnormal_command": 20}
    for scenario, label in expected.items():
        alert, result, _ = _analyze(scenario, ticks[scenario])
        assert result.available and result.hypotheses[0].label == label, scenario
        valid = {e.id for e in alert.evidence}
        assert all(set(h.evidence_ids) <= valid for h in result.hypotheses), scenario
        assert "MOCK" in result.explanation and result.actions, scenario


def test_routing_uses_the_expected_tiers():
    _, tamper, _ = _analyze("logic_tamper", 120)
    _, spoof, _ = _analyze("spoofed_reading", 140)
    assert tamper.tier_used == "ultra" and spoof.tier_used == "super"


def test_apply_result_never_lowers_severity():
    alert, result, _ = _analyze("logic_tamper", 120)
    before = alert.severity
    result.suggested_severity = Severity.info
    apply_result(alert, result)
    assert alert.severity == before and alert.hypotheses and alert.operator_explanation
    assert alert.triage_tier == "ultra"
    result.suggested_severity = Severity.critical
    apply_result(alert, result)
    assert alert.severity == Severity.critical


def test_same_evidence_is_analyzed_once_and_cache_is_shared():
    alert, frames, kmap = _alert_for("logic_tamper", 120)
    pipeline = AnalysisPipeline(LLMClient(), kmap)
    assert pipeline.analyze(alert, frames) is not None
    assert pipeline.analyze(alert, frames) is None
    assert pipeline.stats["skipped"] == 1 and pipeline.stats["triage_calls"] == 1
    other = alert.model_copy() if hasattr(alert, "model_copy") else Alert(
        id="A-0002", ts=alert.ts, severity=alert.severity, title=alert.title, evidence=alert.evidence)
    other.id = "A-0002"
    assert pipeline.analyze(other, frames) is not None
    assert pipeline.stats["cache_hits"] == 1 and pipeline.stats["triage_calls"] == 1


def test_deep_call_budget_is_enforced():
    alert, frames, kmap = _alert_for("spoofed_reading", 140)
    pipeline = AnalysisPipeline(LLMClient(), kmap, max_deep_calls=0)
    result = pipeline.analyze(alert, frames)
    assert result.hypotheses == [] and result.explanation
    assert any("budget" in n for n in result.notes)
    assert pipeline.stats["deep_calls"] == 0


class _FailingLLM:
    is_mock = False
    usage = []

    def generate_json(self, *args, **kwargs):
        raise LLMError("service down")


def test_model_failure_leaves_the_rule_based_alert_intact():
    alert, frames, kmap = _alert_for("logic_tamper", 120)
    pipeline = AnalysisPipeline(_FailingLLM(), kmap)
    result = pipeline.analyze(alert, frames)
    assert result.available is False and "unavailable" in result.explanation
    assert pipeline.stats["failures"] == 1
    before = alert.severity
    apply_result(alert, result)
    assert alert.severity == before and alert.hypotheses == []
