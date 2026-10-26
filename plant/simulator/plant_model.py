"""Physics and PLC-mirror for a small synthetic water treatment plant.

Flow of water: source -> raw tank (LT-101) -> intake pump P-101 -> treatment
-> treated tank (LT-301) -> distribution pump P-301 -> network (PT-301).
Chlorine is dosed by P-201 while P-101 runs and measured by AT-201.

The simulator mirrors plant/plc_programs/water_plant_baseline.st; that file is
analyzed statically and is never executed. All data is synthetic.
"""
import math
import random
from typing import Callable, Dict, Optional

from plant.simulator import interlocks as il

SOURCE_INFLOW = 0.30        # raw tank refill, % per tick
INTAKE_OUTFLOW = 0.60       # raw tank drain while P-101 runs, % per tick
TREATED_INFLOW = 0.56       # treated tank fill while P-101 runs, % per tick
DEMAND_BASE = 0.28          # treated tank drain while P-301 runs, % per tick
DOSE_RATE = 0.12            # ppm per tick while P-201 runs
DECAY_FLOW = 0.020          # chlorine decay per tick while water flows
DECAY_IDLE = 0.005          # chlorine decay per tick without flow
FLOW_NOMINAL = 120.0        # m3/h
NOISE = {"LT-101": 0.15, "FT-101": 1.5, "AT-201": 0.02, "LT-301": 0.15, "PT-301": 0.03}

SETPOINTS = {
    "baseline": {"chlorine_stop": 1.8},
    "tampered": {"chlorine_stop": 99.0},
}

SensorOverride = Callable[[float, random.Random], float]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PlantSim:
    def __init__(self, seed: int = 42, variant: str = "baseline"):
        self.rng = random.Random(seed)
        self.variant = variant
        self.tick = 0
        # true physical state
        self.raw = 60.0
        self.treated = 60.0
        self.chlorine = 1.5
        # controller memory and pump state
        self.auto = {"P-101": True, "P-201": False, "P-301": True}
        self.status = {"P-101": True, "P-201": False, "P-301": True}
        self.cmd = dict(self.status)
        self.hmi_cmd = {"P-201": False, "P-301": False}   # external command bits
        # scenario hooks
        self.sensor_override: Dict[str, SensorOverride] = {}
        self.on_tick: Optional[Callable[["PlantSim"], None]] = None
        self.scenario_name = "normal"
        self.scenario_age = 0
        self.last_trips: Dict[str, list] = {}

    # ------------------------------------------------------------ helpers
    def reset_state(self) -> None:
        """Back to the nominal starting state. The tick counter keeps counting, the noise generator continues."""
        self.raw, self.treated, self.chlorine = 60.0, 60.0, 1.5
        self.auto = {"P-101": True, "P-201": False, "P-301": True}
        self.status = {"P-101": True, "P-201": False, "P-301": True}
        self.cmd = dict(self.status)
        self.hmi_cmd = {"P-201": False, "P-301": False}
        self.sensor_override.clear()
        self.on_tick = None
        self.variant = "baseline"
        self.scenario_name = "normal"
        self.scenario_age = 0
        self.last_trips = {}

    def set_variant(self, variant: str) -> None:
        if variant not in il.UNWIRED:
            raise ValueError(f"unknown program variant: {variant}")
        self.variant = variant

    def _flow_factor(self) -> float:
        """Intake flow collapses when the raw tank is nearly empty (dry run)."""
        return _clamp(self.raw / 8.0, 0.0, 1.0)

    def _true_signals(self) -> Dict[str, float]:
        flow = FLOW_NOMINAL * self._flow_factor() if self.status["P-101"] else 0.0
        pressure = 0.6 + 0.022 * self.treated + (1.9 if self.status["P-301"] else 0.0)
        return {"LT-101": self.raw, "FT-101": flow, "AT-201": self.chlorine,
                "LT-301": self.treated, "PT-301": pressure}

    def _reported_signals(self) -> Dict[str, float]:
        reported = {}
        for tag, true_value in self._true_signals().items():
            override = self.sensor_override.get(tag)
            if override is not None:
                reported[tag] = override(true_value, self.rng)
            else:
                reported[tag] = true_value + self.rng.gauss(0.0, NOISE[tag])
        return reported

    # --------------------------------------------------------------- step
    def step(self) -> Dict:
        if self.on_tick is not None:
            self.on_tick(self)

        rep = self._reported_signals()
        status = dict(self.status)
        trips: Dict[str, list] = {}

        # --- P-101 intake pump (mirrors ST scan order)
        if rep["LT-101"] >= 50.0 and rep["LT-301"] < 85.0:
            self.auto["P-101"] = True
        if rep["LT-101"] < 30.0 or rep["LT-301"] > 90.0:
            self.auto["P-101"] = False
        cmd101 = self.auto["P-101"]
        trips["P-101"] = il.tripping("P-101", self.variant, rep, status)
        status["P-101"] = cmd101 and not trips["P-101"]

        # --- P-201 chlorine dosing pump
        stop_at = SETPOINTS[self.variant]["chlorine_stop"]
        if status["P-101"] and rep["AT-201"] < 1.2:
            self.auto["P-201"] = True
        if (not status["P-101"]) or rep["AT-201"] > stop_at:
            self.auto["P-201"] = False
        cmd201 = self.auto["P-201"] or self.hmi_cmd["P-201"]
        trips["P-201"] = il.tripping("P-201", self.variant, rep, status)
        status["P-201"] = cmd201 and not trips["P-201"]

        # --- P-301 distribution pump
        if rep["LT-301"] >= 30.0:
            self.auto["P-301"] = True
        if rep["LT-301"] < 20.0:
            self.auto["P-301"] = False
        cmd301 = self.auto["P-301"] or self.hmi_cmd["P-301"]
        trips["P-301"] = il.tripping("P-301", self.variant, rep, status)
        status["P-301"] = cmd301 and not trips["P-301"]

        self.cmd = {"P-101": cmd101, "P-201": cmd201, "P-301": cmd301}
        self.status = status
        self.last_trips = trips

        # --- physics for this tick
        flow_factor = self._flow_factor()
        p101 = 1.0 if status["P-101"] else 0.0
        p301 = 1.0 if status["P-301"] else 0.0
        demand = DEMAND_BASE * (1.0 + 0.25 * math.sin(2.0 * math.pi * self.tick / 300.0)) * p301
        self.raw = _clamp(self.raw + SOURCE_INFLOW - INTAKE_OUTFLOW * p101 * flow_factor, 0.0, 100.0)
        self.treated = _clamp(self.treated + TREATED_INFLOW * p101 * flow_factor - demand, 0.0, 100.0)
        decay = DECAY_FLOW if status["P-101"] else DECAY_IDLE
        dose = DOSE_RATE if status["P-201"] else 0.0
        self.chlorine = max(0.0, self.chlorine + dose - decay * self.chlorine)

        self.tick += 1
        self.scenario_age += 1
        return {
            "tick": self.tick,
            "values": {tag: round(value, 3) for tag, value in rep.items()},
            "status": dict(status),
            "commands": dict(self.cmd),
            "scenario": self.scenario_name,
        }

    def truth(self) -> Dict[str, float]:
        """Ground truth for tests and the demo panel (never used by detection)."""
        return {"LT-101": self.raw, "LT-301": self.treated, "AT-201": self.chlorine}
