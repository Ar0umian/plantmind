import os

os.environ["MOCK_LLM"] = "1"

from agent.detector import Detector
from agent.telemetry_store import TelemetryStore, slope
from core.contracts import TelemetryFrame
from knowledge.map_builder import build_knowledge_map
from plant.simulator.runner import SimulatorRunner

ST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "plant", "plc_programs", "water_plant_baseline.st")


def _kmap():
    with open(ST_PATH, encoding="utf-8") as handle:
        return build_knowledge_map(handle.read())[0]


def _frames(scenario, ticks):
    runner = SimulatorRunner(interval_s=0.0, seed=7)
    if scenario != "normal":
        runner.start_scenario(scenario)
    return [runner.step_once() for _ in range(ticks)]


def _detect(frames):
    detector = Detector(_kmap())
    found = []          # (tick, evidence)
    for frame in frames:
        for evidence in detector.process(frame):
            found.append((frame.tick, evidence))
    return found


def test_normal_operation_raises_no_evidence():
    assert _detect(_frames("normal", 1500)) == []


def test_logic_tamper_is_caught_as_interlock_violation():
    found = _detect(_frames("logic_tamper", 120))
    hits = [(t, e) for t, e in found if e.kind == "interlock_violation"]
    assert hits and "IL-04" in hits[0][1].summary
    assert hits[0][0] <= 75


def test_spoofed_reading_is_caught_by_physics_not_by_the_plc():
    found = _detect(_frames("spoofed_reading", 140))
    kinds = [e.kind for _, e in found]
    assert "interlock_violation" not in kinds          # the PLC was fooled
    trend = [t for t, e in found if "LT-101" in e.tags and "level" in e.summary.lower()]
    assert trend and trend[0] <= 30
    assert any("FT-101" in e.tags for _, e in found)   # flow collapse found later


def test_sensor_fault_flatline_is_caught():
    found = _detect(_frames("sensor_fault", 60))
    assert any(e.kind == "stale_value" and "AT-201" in e.tags for _, e in found)
    assert any(e.kind == "physical_inconsistency" and "P-201" in e.tags for _, e in found)


def test_abnormal_command_is_caught_quickly():
    found = _detect(_frames("abnormal_command", 20))
    targets = {tag for t, e in found if e.kind == "command_anomaly" and t <= 5 for tag in e.tags}
    assert {"P-201", "P-301"} <= targets


def test_detector_never_uses_the_scenario_label():
    frames = _frames("abnormal_command", 60)
    hidden = [TelemetryFrame(ts=f.ts, tick=f.tick, values=f.values, status=f.status,
                             commands=f.commands, scenario="hidden") for f in frames]
    a = [(t, e.kind, e.summary) for t, e in _detect(frames)]
    b = [(t, e.kind, e.summary) for t, e in _detect(hidden)]
    assert a == b and a


def _mk(tick, p101, p201):
    return TelemetryFrame(
        ts=float(tick), tick=tick,
        values={"LT-101": 50.0 - tick * 0.1, "FT-101": 120.0 if p101 else 0.0 + tick * 0.01,
                "AT-201": 1.0 + tick * 0.001, "LT-301": 60.0 + tick * 0.01, "PT-301": 4.0 + tick * 0.001},
        status={"P-101": p101, "P-201": p201, "P-301": True},
        commands={"P-101": p101, "P-201": p201, "P-301": True})


def test_episode_clears_and_retriggers():
    detector = Detector(_kmap(), clear_after=5)
    # IL-03: P-101 stopped while P-201 keeps running -> violation episode
    sequence = ([(False, True)] * 3 + [(True, False)] * 8 + [(False, True)] * 3)
    started = []
    for i, (p101, p201) in enumerate(sequence, start=1):
        started += [e for e in detector.process(_mk(i, p101, p201)) if "IL-03" in e.summary]
    assert len(started) == 2
    assert [e.id for e in detector.history if "IL-03" in e.summary] == [e.id for e in started]


def test_evidence_ids_are_sequential():
    detector = Detector(_kmap())
    for frame in _frames("abnormal_command", 10):
        detector.process(frame)
    assert [e.id for e in detector.history] == ["EV-0001", "EV-0002"]


def test_store_window_and_slope():
    store = TelemetryStore(maxlen=5)
    for i in range(8):
        store.add(_mk(i, True, False))
    assert len(store) == 5 and store.latest().tick == 7
    assert [f.tick for f in store.window(3)] == [5, 6, 7]
    assert abs(slope([0.0, 1.0, 2.0, 3.0]) - 1.0) < 1e-9
    assert slope([5.0]) == 0.0
