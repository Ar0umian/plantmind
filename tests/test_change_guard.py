import os

os.environ["MOCK_LLM"] = "1"

from agent.engine import APPROVED_PROGRAM, PROGRAMS, Engine
from agent.reasoner import mock_reasoner
from core.contracts import Alert, Evidence, Severity
from core.llm_client import LLMClient, LLMError
from knowledge.change_guard import (AssessedFinding, ChangeGuard, GuardAssessment, GuardService)

BASELINE = APPROVED_PROGRAM.read_text(encoding="utf-8")
TAMPERED = PROGRAMS["tampered"].read_text(encoding="utf-8")


def _edit(old, new, text=BASELINE):
    assert old in text, old
    return text.replace(old, new, 1)


def _guard(llm=None):
    return ChangeGuard(BASELINE, llm=llm)


def _kinds(result):
    return [(f.kind, f.interlock_id, f.rule_severity.value) for f in result.report.findings]


def test_identical_program_has_no_findings_and_no_model_call():
    result = _guard(LLMClient()).compare(BASELINE)
    assert result.report.findings == [] and result.mode == "none"
    assert result.report.overall_severity == Severity.info and result.diff == ""


def test_comment_only_change_is_not_a_finding():
    result = _guard().compare(_edit("(* Intake pump run *)", "(* Intake pump running state *)"))
    assert result.report.findings == []


def test_tampered_program_bypass_and_setpoint_are_caught():
    result = _guard().compare(TAMPERED)
    report = result.report
    assert report.overall_severity == Severity.critical
    first = report.findings[0]
    assert (first.id, first.kind, first.interlock_id) == ("F-001", "modified", "IL-04")
    assert first.rule_severity == Severity.critical and "bypassed" in first.summary
    ids = {m.technique_id for m in first.mitre}
    assert {"T0889", "T0837"} <= ids
    setpoint = next(f for f in report.findings if f.interlock_id is None)
    assert setpoint.rule_severity == Severity.high
    assert "beyond the approved limit of IL-04" in setpoint.hazard
    assert [m.technique_id for m in setpoint.mitre] == ["T0836"]
    assert [f.id for f in report.findings] == ["F-001", "F-002"]
    assert "-IF NOT P_101_RUN OR AT_201 > 1.8 THEN" in result.diff
    assert "+IF NOT P_101_RUN OR AT_201 > 99.0 THEN" in result.diff


def test_removed_interlock_is_critical():
    text = _edit("NOT (IL_05 OR IL_06)", "NOT IL_05", _edit("IL_06 := PT_301 > 6.0;\n", ""))
    result = _guard().compare(text)
    assert ("removed", "IL-06", "critical") in _kinds(result)
    assert result.report.overall_severity == Severity.critical


def test_weakened_and_tightened_thresholds():
    weak = _guard().compare(_edit("IL_01 := LT_101 < 15.0;", "IL_01 := LT_101 < 5.0;"))
    assert _kinds(weak) == [("modified", "IL-01", "high")] and "weakened" in weak.report.findings[0].summary
    strong = _guard().compare(_edit("IL_01 := LT_101 < 15.0;", "IL_01 := LT_101 < 25.0;"))
    assert _kinds(strong) == [("modified", "IL-01", "low")] and "tightened" in strong.report.findings[0].summary
    high_side = _guard().compare(_edit("IL_04 := AT_201 > 4.0;", "IL_04 := AT_201 > 6.0;"))
    assert _kinds(high_side) == [("modified", "IL-04", "high")]


def test_added_interlock_wired_and_unwired():
    base_line = "IL_06 := PT_301 > 6.0;\n"
    unwired = _guard().compare(_edit(base_line, base_line + "IL_07 := PT_301 > 7.0;\n"))
    assert _kinds(unwired) == [("added", "IL-07", "medium")]
    assert "protects nothing" in unwired.report.findings[0].hazard
    wired_text = _edit("NOT (IL_05 OR IL_06)", "NOT (IL_05 OR IL_06 OR IL_07)",
                       _edit(base_line, base_line + "IL_07 := PT_301 > 7.0;\n"))
    wired = _guard().compare(wired_text)
    assert _kinds(wired) == [("added", "IL-07", "low")]


def test_alarm_removed_and_relaxed():
    removed = _guard().compare(_edit("AL_03 := PT_301 > 5.0;\n", ""))
    assert _kinds(removed) == [("removed", "AL-03", "medium")]
    assert {m.technique_id for m in removed.report.findings[0].mitre} == {"T0878", "T0838"}
    relaxed = _guard().compare(_edit("AL_01 := LT_101 < 25.0;", "AL_01 := LT_101 < 10.0;"))
    assert _kinds(relaxed) == [("modified", "AL-01", "medium")]


def test_new_external_command_path_is_flagged():
    result = _guard().compare(_edit("P_101_CMD := P_101_AUTO;", "P_101_CMD := P_101_AUTO OR P_101_HMI_CMD;"))
    assert _kinds(result) == [("added", None, "medium")]
    assert "P-101" in result.report.findings[0].summary


def test_unanalyzable_statement_is_reported_not_ignored():
    result = _guard().compare(_edit("END_PROGRAM", "FOO := (LT_101 < 3) AND TRUE;\nEND_PROGRAM"))
    assert result.report.findings and result.report.findings[0].rule_severity == Severity.medium
    assert "could not be analyzed" in result.report.findings[0].summary


def test_unexplained_text_change_gets_a_generic_low_finding():
    result = _guard().compare(_edit("P_301_AUTO : BOOL := TRUE;", "P_301_AUTO : BOOL := FALSE;"))
    assert len(result.report.findings) == 1 and result.report.findings[0].rule_severity == Severity.low
    assert "no change to the protective" in result.report.findings[0].summary


def test_mock_assessment_keeps_rule_text_and_labels_the_mode():
    result = _guard(LLMClient()).compare(TAMPERED)
    assert result.mode == "mock" and result.report.llm_available is True
    assert all(f.hazard and f.recommendation for f in result.report.findings)


class _FailingLLM:
    is_mock = False

    def generate_json(self, *args, **kwargs):
        raise LLMError("down")


def test_model_failure_keeps_deterministic_report():
    result = _guard(_FailingLLM()).compare(TAMPERED)
    assert result.mode == "unavailable" and result.report.llm_available is False
    assert result.report.overall_severity == Severity.critical
    assert all(f.hazard and f.recommendation for f in result.report.findings)


class _ScriptedLLM:
    is_mock = False

    def generate_json(self, tier, system, user, schema, mock=None, **kwargs):
        return GuardAssessment(findings=[
            AssessedFinding(finding_id="F-001", severity=Severity.info,
                            hazard="  Model   hazard\ntext ", recommendation="Model advice"),
            AssessedFinding(finding_id="F-099", severity=Severity.critical,
                            hazard="invented", recommendation="invented"),
            AssessedFinding(finding_id="F-002", severity=Severity.critical,
                            hazard="", recommendation="")])


def test_model_can_raise_but_never_lower_and_unknown_ids_are_ignored():
    result = _guard(_ScriptedLLM()).compare(TAMPERED)
    first, second = result.report.findings
    assert result.mode == "live"
    assert first.llm_severity == Severity.info and first.final_severity() == Severity.critical
    assert first.hazard == "Model hazard text" and first.recommendation == "Model advice"
    assert second.rule_severity == Severity.high and second.final_severity() == Severity.critical
    assert second.hazard                                   # empty model text did not erase the rule text
    assert result.report.overall_severity == Severity.critical
    assert all("invented" not in f.hazard for f in result.report.findings)


def test_service_caches_decides_and_validates():
    service = GuardService(BASELINE, llm=LLMClient())
    first = service.check(TAMPERED, source="upload")
    assert service.check(TAMPERED) is first and len(service.results()) == 1
    assert service.get(first.report.candidate_hash) is first
    assert service.decide(first.report.candidate_hash, "rejected").report.decision == "rejected"
    for bad, error in (("maybe", ValueError),):
        try:
            service.decide(first.report.candidate_hash, bad)
            assert False
        except error:
            pass
    try:
        service.decide("deadbeef", "approved")
        assert False
    except KeyError:
        pass
    service.reset()
    assert service.results() == []


def test_engine_checks_the_running_program_when_the_scenario_changes_it():
    engine = Engine(interval_s=0.0)
    engine.step()
    assert engine.guard_running() is None                           # baseline matches the approved program
    engine.start_scenario("logic_tamper")
    engine.step()
    result = engine.guard_running()
    assert result is not None and result.report.overall_severity == Severity.critical
    assert "running program" in result.source
    engine.stop_scenario()
    engine.step()
    assert engine.guard_running() is None


def test_guard_finding_feeds_the_alert_analysis_context():
    engine = Engine(interval_s=0.0)
    engine.start_scenario("logic_tamper")
    for _ in range(120):
        engine.step()
    alert = engine.alerts()[0]
    assert alert.hypotheses[0].label == "logic_tampering"
    context = engine._guard_context(alert)
    assert "differs from the approved program" in context and "IL-04" in context


def test_mock_reasoner_uses_guard_context():
    alert = Alert(id="A-1", ts=1.0, severity=Severity.medium, title="t",
                  evidence=[Evidence(id="EV-0001", kind="physical_inconsistency", summary="s", tags=[], ts=1.0)])
    plain = mock_reasoner(alert)
    informed = mock_reasoner(alert, "Change Guard: the PLC program currently running differs from the approved program.")
    assert plain.hypotheses[0].label == "spoofing"
    assert informed.hypotheses[0].label == "logic_tampering"
