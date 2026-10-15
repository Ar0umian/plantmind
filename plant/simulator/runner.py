"""Threaded runner around PlantSim; implements the PlantRunner interface.

Run a quick text view without threads:
    python -m plant.simulator.runner --scenario logic_tamper --ticks 120 --every 10
"""
import argparse
import threading
import time
from collections import deque
from typing import Deque, List, Optional

from core.config import get_settings
from core.contracts import TelemetryFrame
from plant.scenarios.scenarios import SCENARIO_NAMES, activate, deactivate
from plant.simulator.plant_model import PlantSim


class SimulatorRunner:
    def __init__(self, interval_s: Optional[float] = None, ticks_per_frame: int = 1,
                 seed: int = 42, history: int = 3600):
        self.interval_s = interval_s if interval_s is not None else get_settings().telemetry_interval_s
        self.ticks_per_frame = max(1, ticks_per_frame)
        self.sim = PlantSim(seed=seed)
        self._frames: Deque[TelemetryFrame] = deque(maxlen=history)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------ stepping
    def step_once(self) -> TelemetryFrame:
        """Advance the plant by one frame (ticks_per_frame ticks) and store it."""
        with self._lock:
            raw = None
            for _ in range(self.ticks_per_frame):
                raw = self.sim.step()
            frame = TelemetryFrame(ts=time.time(), tick=raw["tick"], values=raw["values"],
                                   status=raw["status"], commands=raw["commands"],
                                   scenario=raw["scenario"])
            self._frames.append(frame)
            return frame

    def _loop(self) -> None:
        while self._running:
            started = time.time()
            self.step_once()
            time.sleep(max(0.0, self.interval_s - (time.time() - started)))

    # -------------------------------------------------- PlantRunner interface
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def list_scenarios(self) -> List[str]:
        return list(SCENARIO_NAMES)

    def start_scenario(self, name: str) -> None:
        with self._lock:
            activate(self.sim, name)

    def stop_scenario(self) -> None:
        with self._lock:
            deactivate(self.sim)

    def latest_frame(self) -> Optional[TelemetryFrame]:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def recent_frames(self, n: int = 60) -> List[TelemetryFrame]:
        with self._lock:
            return list(self._frames)[-n:]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Text view of the plant simulator")
    parser.add_argument("--scenario", default="normal", choices=SCENARIO_NAMES)
    parser.add_argument("--ticks", type=int, default=120)
    parser.add_argument("--every", type=int, default=10)
    args = parser.parse_args()

    runner = SimulatorRunner(interval_s=0.0)
    if args.scenario != "normal":
        runner.start_scenario(args.scenario)
    print(f"scenario: {args.scenario}")
    print("tick  LT-101  FT-101  AT-201  LT-301  PT-301  P-101 P-201 P-301  cmd(101,201,301)")
    for _ in range(args.ticks):
        frame = runner.step_once()
        if frame.tick % args.every == 0:
            v, s, c = frame.values, frame.status, frame.commands
            print(f"{frame.tick:4d} {v['LT-101']:7.1f} {v['FT-101']:7.1f} {v['AT-201']:7.2f} "
                  f"{v['LT-301']:7.1f} {v['PT-301']:7.2f}  {int(s['P-101']):4d} {int(s['P-201']):5d} "
                  f"{int(s['P-301']):5d}   {int(c['P-101'])}{int(c['P-201'])}{int(c['P-301'])}")


if __name__ == "__main__":
    _main()
