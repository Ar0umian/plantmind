import os

os.environ["MOCK_LLM"] = "1"

from agent.context import summarize_frames
from agent.engine import load_approved_map
from agent.reasoner import REASONER_SYSTEM, ReasonerOutput, run_reasoner, validate_output
from core.contracts import Alert, Evidence, Hypothesis, Severity, TelemetryFrame


def _frames(at_values, p101=True, n=None):
    n = n or len(at_values)
    return [TelemetryFrame(ts=float(i), tick=i, values={"AT-201": at_values[i % len(at_values)], "LT-101": 40.0 + i * 0.01},
                           status={"P-101": p101, "P-201": False}, commands={"P-101": p101, "P-201": False})
            for i in range(n)]


def _alert():
    ev = Evidence(id="EV-0001", kind="interlock_violation", summary="s", tags=["AT-201"], ts=1.0)
    return Alert(id="A-0001", ts=1.0, severity=Severity.high, title="t", evidence=[ev])


def _hyp(ids):
    return Hypothesis(label="logic_tampering", confidence=0.8, reasoning="r", evidence_ids=ids)


def test_summary_flags_a_constant_reading_and_shows_noise_otherwise():
    flat = summarize_frames(_frames([0.0], n=10))
    assert "AT-201:" in flat and "EXACTLY constant" in flat and "std=0.000" in flat
    noisy = summarize_frames(_frames([1.0, 1.1, 0.9, 1.05], n=12))
    assert "EXACTLY constant" not in noisy.split("AT-201:")[1].split("\n")[0]
    assert "std=0.0" in noisy


def test_summary_reports_how_long_each_pump_has_been_in_its_state():
    frames = _frames([1.0, 1.1], p101=True, n=7)
    frames[0].status["P-101"] = False
    text = summarize_frames(frames)
    assert "P-101: ON for the last 6 of 7 frames" in text
    assert "P-201: OFF for the last 7 of 7 frames" in text


def test_validator_accepts_change_guard_finding_ids_only_when_they_are_provided():
    out = ReasonerOutput(hypotheses=[_hyp(["EV-0001", "F-001", "IL-04"])], operator_explanation="x")
    with_guard, notes = validate_output(out, _alert(), {"F-001", "F-002"})
    assert with_guard.hypotheses[0].evidence_ids == ["EV-0001", "F-001"]
    assert any("IL-04" in n for n in notes)
    without_guard, _ = validate_output(out, _alert())
    assert without_guard.hypotheses[0].evidence_ids == ["EV-0001"]


def test_fallback_hypothesis_cites_only_real_evidence():
    out = ReasonerOutput(hypotheses=[_hyp(["IL-04"])], operator_explanation="x")
    clean, _ = validate_output(out, _alert(), {"F-001"})
    assert clean.hypotheses[0].label == "unknown" and clean.hypotheses[0].evidence_ids == ["EV-0001"]


def test_prompt_explains_telemetry_facts_and_citation_rules():
    assert "std" in REASONER_SYSTEM and "spoofing, not to a frozen sensor" in REASONER_SYSTEM
    assert "finding IDs (like F-001)" in REASONER_SYSTEM and "Never put interlock IDs" in REASONER_SYSTEM


class _Scripted:
    is_mock = False

    def __init__(self, output):
        self.output, self.prompts = output, []

    def generate_json(self, tier, system, user, schema, mock=None, **kwargs):
        self.prompts.append(user)
        return self.output


def test_reasoner_keeps_finding_ids_named_in_the_change_guard_context():
    llm = _Scripted(ReasonerOutput(hypotheses=[_hyp(["EV-0001", "F-001"])], operator_explanation="x"))
    guard_context = "Change Guard: the PLC program currently running differs from the approved program.\n- F-001 [critical] bypass"
    out, notes = run_reasoner(llm, "ultra", _alert(), load_approved_map(), _frames([1.0, 1.1], n=5), guard_context)
    assert out.hypotheses[0].evidence_ids == ["EV-0001", "F-001"] and not notes
    assert "std=" in llm.prompts[0] and "F-001" in llm.prompts[0]
    plain, notes = run_reasoner(llm, "ultra", _alert(), load_approved_map(), _frames([1.0], n=5), "")
    assert plain.hypotheses[0].evidence_ids == ["EV-0001"] and any("F-001" in n for n in notes)
