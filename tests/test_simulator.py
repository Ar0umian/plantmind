import os
import re

os.environ["MOCK_LLM"] = "1"

from core.contracts import PlantRunner, TelemetryFrame
from plant.scenarios.scenarios import SCENARIO_NAMES, activate
from plant.simulator import interlocks as il
from plant.simulator.plant_model import PlantSim
from plant.simulator.runner import SimulatorRunner

ST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plant", "plc_programs")


def _read(name):
    with open(os.path.join(ST_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def _run(name, ticks, seed=7):
    sim = PlantSim(seed=seed)
    if name != "normal":
        activate(sim, name)
    frames = []
    for _ in range(ticks):
        frame = sim.step()
        frames.append((frame, dict(sim.truth())))
    return sim, frames


def _conflicts(frame):
    return [p for p in frame["commands"] if frame["commands"][p] and not frame["status"][p]]


def test_normal_run_is_stable_and_conflict_free():
    sim, frames = _run("normal", 1500)
    assert all(not _conflicts(f) for f, _ in frames)
    assert all(10.0 < truth["LT-101"] < 95.0 for _, truth in frames)
    assert all(10.0 < truth["LT-301"] < 95.0 for _, truth in frames)
    assert all(0.0 < truth["AT-201"] < 3.0 for _, truth in frames)


def test_same_seed_same_output():
    _, a = _run("normal", 200, seed=3)
    _, b = _run("normal", 200, seed=3)
    assert [f["values"] for f, _ in a] == [f["values"] for f, _ in b]


def test_sensor_fault_flatline_hides_real_overdose():
    _, frames = _run("sensor_fault", 120)
    reported = [f["values"]["AT-201"] for f, _ in frames]
    assert all(value == 0.0 for value in reported)
    assert max(truth["AT-201"] for _, truth in frames) > 4.0


def test_spoofed_reading_hides_draining_tank():
    _, frames = _run("spoofed_reading", 120)
    reported = [f["values"]["LT-101"] for f, _ in frames]
    assert all(30.0 < value < 38.0 for value in reported)
    assert frames[80][1]["LT-101"] < 12.0
    assert frames[119][0]["values"]["FT-101"] < 100.0   # flow collapses while pump runs
    assert frames[119][0]["status"]["P-101"] is True


def test_logic_tamper_overdose_without_trip():
    _, frames = _run("logic_tamper", 80)
    overdose_running = [f for f, _ in frames
                        if f["values"]["AT-201"] > 4.0 and f["status"]["P-201"]]
    assert len(overdose_running) > 10


def test_baseline_logic_trips_on_overdose_but_tampered_does_not():
    reported = {"LT-101": 50.0, "LT-301": 60.0, "AT-201": 4.5, "PT-301": 4.0, "FT-101": 120.0}
    status = {"P-101": True, "P-201": True, "P-301": True}
    assert "IL-04" in il.tripping("P-201", "baseline", reported, status)
    assert "IL-04" not in il.tripping("P-201", "tampered", reported, status)


def test_abnormal_command_burst_is_refused_by_interlocks():
    _, frames = _run("abnormal_command", 60)
    first = [f for f, _ in frames[:45]]
    assert sum(1 for f in first if _conflicts(f)) >= 40
    assert all(not f["status"]["P-201"] and not f["status"]["P-301"] for f in first)


def test_st_files_mirror_interlock_definitions():
    baseline = _read("water_plant_baseline.st")
    for definition in il.INTERLOCKS:
        name = definition.id.replace("-", "_")
        tag, op, value = definition.conditions[0]
        if isinstance(value, bool):
            expected = f"{name} := NOT {tag.replace('-', '_')}_RUN;"
        else:
            expected = f"{name} := {tag.replace('-', '_')} {op} {value};"
        assert expected in baseline, expected


def test_tampered_st_differs_by_exactly_the_bypass():
    baseline = _read("water_plant_baseline.st")
    tampered = _read("water_plant_tampered.st")
    assert "NOT (IL_03 OR IL_04)" in baseline
    assert "NOT (IL_03 OR IL_04)" not in tampered
    assert "AT_201 > 99.0" in tampered
    assert re.search(r"IL_04 := AT_201 > 4\.0;", tampered)   # still computed, no longer wired


def test_runner_implements_interface_and_switches_scenarios():
    runner = SimulatorRunner(interval_s=0.0)
    assert isinstance(runner, PlantRunner)
    assert runner.list_scenarios() == SCENARIO_NAMES
    frame = runner.step_once()
    assert isinstance(frame, TelemetryFrame)
    assert set(frame.values) == {"LT-101", "FT-101", "AT-201", "LT-301", "PT-301"}
    runner.start_scenario("logic_tamper")
    assert runner.step_once().scenario == "logic_tamper"
    runner.stop_scenario()
    assert runner.step_once().scenario == "normal"
    assert len(runner.recent_frames(10)) == 3
