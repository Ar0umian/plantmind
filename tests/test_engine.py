import os
import time

os.environ["MOCK_LLM"] = "1"

from agent.alerts import AlertManager
from agent.engine import Engine
from core.contracts import Evidence


def _engine():
    return Engine(interval_s=0.0)


def _run(engine, ticks):
    for _ in range(ticks):
        engine.step()


def test_normal_operation_creates_no_alerts():
    engine = _engine()
    _run(engine, 300)
    assert engine.alerts() == [] and engine.history() == []


def test_logic_tamper_creates_one_high_alert_about_il04():
    engine = _engine()
    engine.start_scenario("logic_tamper")
    _run(engine, 120)
    alerts = engine.alerts()
    assert len(alerts) == 1
    assert alerts[0].severity.value == "high"
    assert "IL-04" in alerts[0].title
    assert any("IL-04" in e.summary for e in alerts[0].evidence)
    assert alerts[0].status == "open"


def test_one_incident_one_alert():
    engine = _engine()
    engine.start_scenario("sensor_fault")
    _run(engine, 60)
    alerts = engine.alerts()
    assert len(alerts) == 1 and len(alerts[0].evidence) == 2
    assert "more finding" in alerts[0].title

    engine.start_scenario("spoofed_reading")          # scenario start resets detection
    assert engine.alerts() == []
    _run(engine, 140)
    alerts = engine.alerts()
    assert len(alerts) == 1 and len(alerts[0].evidence) >= 2   # level trend + flow loss merged


def test_abnormal_command_alert_is_medium():
    engine = _engine()
    engine.start_scenario("abnormal_command")
    _run(engine, 20)
    alerts = engine.alerts()
    assert len(alerts) == 1 and alerts[0].severity.value == "medium"
    assert "command" in alerts[0].title.lower()


def test_decisions_are_logged_and_validated():
    engine = _engine()
    engine.start_scenario("abnormal_command")
    _run(engine, 10)
    alert_id = engine.alerts()[0].id
    assert engine.decide(alert_id, "approved").status == "approved"
    assert engine.decisions()[-1]["decision"] == "approved"
    try:
        engine.decide(alert_id, "maybe")
        assert False, "invalid decision must raise"
    except ValueError:
        pass
    try:
        engine.decide("A-9999", "rejected")
        assert False, "unknown alert must raise"
    except KeyError:
        pass


def test_new_evidence_after_a_decision_opens_a_new_alert():
    manager = AlertManager()
    ev1 = Evidence(id="EV-0001", kind="stale_value", summary="x", tags=["AT-201"], ts=1.0)
    ev2 = Evidence(id="EV-0002", kind="command_anomaly", summary="y", tags=["P-201"], ts=2.0)
    first = manager.ingest([ev1], frame_no=1, ts=1.0)[0]
    manager.decide(first.id, "deferred")
    second = manager.ingest([ev2], frame_no=5, ts=2.0)[0]
    assert second.id != first.id and len(manager.alerts) == 2


def test_merge_window_limits_merging():
    manager = AlertManager(merge_window_frames=10)
    ev1 = Evidence(id="EV-0001", kind="stale_value", summary="x", tags=[], ts=1.0)
    ev2 = Evidence(id="EV-0002", kind="stale_value", summary="y", tags=[], ts=2.0)
    a = manager.ingest([ev1], frame_no=1, ts=1.0)[0]
    b = manager.ingest([ev2], frame_no=50, ts=2.0)[0]
    assert a.id != b.id


def test_background_thread_produces_frames_and_stops():
    engine = Engine(interval_s=0.02)
    engine.start()
    time.sleep(0.4)
    engine.stop()
    count = len(engine.frames(1000))
    assert count >= 5
    time.sleep(0.1)
    assert len(engine.frames(1000)) == count          # stopped


def test_scenario_listing_and_demo_label():
    engine = _engine()
    names = [s["name"] for s in engine.scenarios()]
    assert names[0] == "normal" and "logic_tamper" in names
    engine.start_scenario("spoofed_reading")
    assert engine.demo_scenario == "spoofed_reading"
    engine.stop_scenario()
    assert engine.demo_scenario == "normal"


def test_engine_attaches_model_analysis_to_alerts():
    engine = _engine()
    engine.start_scenario("logic_tamper")
    _run(engine, 120)
    alert = engine.alerts()[0]
    assert alert.hypotheses and alert.hypotheses[0].label == "logic_tampering"
    assert alert.operator_explanation.startswith("[MOCK") and alert.recommended_actions
    assert alert.triage_tier == "ultra"
    assert all(h.evidence_ids and set(h.evidence_ids) <= {e.id for e in alert.evidence}
               for h in alert.hypotheses)
    info = engine.llm_info()
    assert info["enabled"] and info["mock"] is True and info["stats"]["triage_calls"] == 1


def test_analysis_can_be_disabled_and_reset_clears_it():
    engine = Engine(interval_s=0.0, analyze=False)
    engine.start_scenario("abnormal_command")
    _run(engine, 10)
    assert engine.alerts()[0].hypotheses == [] and engine.llm_info()["enabled"] is False

    engine2 = _engine()
    engine2.start_scenario("abnormal_command")
    _run(engine2, 10)
    assert engine2.alerts()[0].hypotheses
    engine2.reset_detection()
    assert engine2.alerts() == [] and engine2.llm_info()["stats"]["triage_calls"] == 1
    _run(engine2, 12)                                  # same scenario evidence again -> new alert, cached
    assert engine2.alerts() and engine2.alerts()[0].hypotheses


def test_background_analysis_thread_fills_in_the_alert():
    engine = Engine(interval_s=0.01)
    engine.start_scenario("abnormal_command")
    engine.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        alerts = engine.alerts()
        if alerts and alerts[0].operator_explanation:
            break
        time.sleep(0.05)
    engine.stop()
    alerts = engine.alerts()
    assert alerts and alerts[0].operator_explanation and alerts[0].hypotheses
