"""Synthetic scenario injection for defensive testing and demos.

Each scenario stages the plant into a suitable starting state (so the demo
reaches the interesting moment quickly) and then changes either how a sensor
is REPORTED, which program variant runs, or which external commands arrive.
Nothing here touches a real device or network.
"""
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from plant.simulator.plant_model import PlantSim

SCENARIO_NAMES = ["normal", "sensor_fault", "spoofed_reading", "logic_tamper", "abnormal_command"]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    stage: Callable[[PlantSim], None]
    per_tick: Optional[Callable[[PlantSim], None]] = None


def _reset(sim: PlantSim) -> None:
    sim.sensor_override.clear()
    sim.hmi_cmd = {"P-201": False, "P-301": False}
    sim.on_tick = None
    sim.set_variant("baseline")


def _pump_running(sim: PlantSim, raw: float = 55.0) -> None:
    sim.raw = raw
    sim.chlorine = 1.5
    sim.auto["P-101"] = True
    sim.status["P-101"] = True


def _stage_normal(sim: PlantSim) -> None:
    pass


def _stage_sensor_fault(sim: PlantSim) -> None:
    _pump_running(sim)
    # Analyzer fails and reads a flat 0.00 ppm (exactly constant).
    sim.sensor_override["AT-201"] = lambda true_value, rng: 0.0


def _stage_spoofed(sim: PlantSim) -> None:
    _pump_running(sim, raw=34.0)
    mean = 34.0
    # Fabricated, plausible-looking level (fresh noise) while the true level falls.
    sim.sensor_override["LT-101"] = lambda true_value, rng: mean + rng.gauss(0.0, 0.15)


def _stage_logic_tamper(sim: PlantSim) -> None:
    _pump_running(sim)
    sim.set_variant("tampered")


def _stage_abnormal_command(sim: PlantSim) -> None:
    sim.raw = 33.0
    sim.treated = 12.0
    sim.chlorine = 1.0
    sim.auto.update({"P-101": False, "P-201": False, "P-301": False})
    sim.status.update({"P-101": False, "P-201": False, "P-301": False})


def _tick_abnormal_command(sim: PlantSim) -> None:
    # External command burst against pumps whose interlocks are active.
    active = sim.scenario_age < 45
    sim.hmi_cmd = {"P-201": active, "P-301": active}


SCENARIOS: Dict[str, Scenario] = {
    "normal": Scenario("normal", "Normal operation", _stage_normal),
    "sensor_fault": Scenario(
        "sensor_fault", "Chlorine analyzer AT-201 fails and reads a flat zero",
        _stage_sensor_fault),
    "spoofed_reading": Scenario(
        "spoofed_reading", "Raw tank level LT-101 is reported falsely while the tank drains",
        _stage_spoofed),
    "logic_tamper": Scenario(
        "logic_tamper", "PLC program modified: IL-04 bypassed and dosing never stops",
        _stage_logic_tamper),
    "abnormal_command": Scenario(
        "abnormal_command", "Unexpected external commands against pumps with active interlocks",
        _stage_abnormal_command, _tick_abnormal_command),
}


def activate(sim: PlantSim, name: str) -> None:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario '{name}', expected one of {SCENARIO_NAMES}")
    scenario = SCENARIOS[name]
    sim.reset_state()
    _reset(sim)
    sim.scenario_name = name
    sim.scenario_age = 0
    scenario.stage(sim)
    sim.on_tick = scenario.per_tick


def deactivate(sim: PlantSim) -> None:
    """Return to normal behaviour without resetting the physical state."""
    _reset(sim)
    sim.scenario_name = "normal"
    sim.scenario_age = 0
