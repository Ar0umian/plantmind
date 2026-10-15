"""Engine: simulator -> detector -> alerts, with an optional background thread.

All public methods are thread-safe (one re-entrant lock). The scenario label is
exposed ONLY as `demo_scenario` for the demo control panel; detection never sees it.
"""
import threading
import time
from pathlib import Path
from typing import List, Optional

from core.config import get_settings
from core.contracts import Alert, Evidence, KnowledgeMap, TelemetryFrame
from agent.alerts import AlertManager
from agent.detector import Detector
from knowledge.map_builder import build_knowledge_map
from plant.scenarios.scenarios import SCENARIOS, SCENARIO_NAMES
from plant.simulator.runner import SimulatorRunner

ROOT = Path(__file__).resolve().parents[1]
APPROVED_PROGRAM = ROOT / "plant" / "plc_programs" / "water_plant_baseline.st"


def load_approved_map() -> KnowledgeMap:
    kmap, _ = build_knowledge_map(APPROVED_PROGRAM.read_text(encoding="utf-8"))
    return kmap


class Engine:
    def __init__(self, runner: Optional[SimulatorRunner] = None, kmap: Optional[KnowledgeMap] = None,
                 interval_s: Optional[float] = None, ticks_per_frame: int = 1):
        self.interval_s = interval_s if interval_s is not None else get_settings().telemetry_interval_s
        self.runner = runner or SimulatorRunner(interval_s=0.0, ticks_per_frame=ticks_per_frame)
        self.kmap = kmap or load_approved_map()
        self.detector = Detector(self.kmap)
        self.alert_manager = AlertManager()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_no = 0

    # ------------------------------------------------------------- stepping
    def step(self) -> TelemetryFrame:
        with self._lock:
            frame = self.runner.step_once()
            self._frame_no += 1
            new = self.detector.process(frame)
            self.alert_manager.ingest(new, self._frame_no, frame.ts)
            return frame

    def _loop(self) -> None:
        while self._running:
            started = time.time()
            self.step()
            time.sleep(max(0.0, self.interval_s - (time.time() - started)))

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

    # ------------------------------------------------------------- scenarios
    def scenarios(self) -> List[dict]:
        return [{"name": n, "description": SCENARIOS[n].description} for n in SCENARIO_NAMES]

    @property
    def demo_scenario(self) -> str:
        """Ground truth label for the demo panel only."""
        with self._lock:
            return self.runner.sim.scenario_name

    def start_scenario(self, name: str, reset: bool = True) -> None:
        with self._lock:
            self.runner.start_scenario(name)
            if reset:
                self.reset_detection()

    def stop_scenario(self) -> None:
        with self._lock:
            self.runner.stop_scenario()

    def reset_detection(self) -> None:
        with self._lock:
            self.detector.reset()
            self.alert_manager.reset()
            self._frame_no = 0

    # ------------------------------------------------------------ read access
    def latest_frame(self) -> Optional[TelemetryFrame]:
        return self.runner.latest_frame()

    def frames(self, n: int = 120) -> List[TelemetryFrame]:
        return self.runner.recent_frames(n)

    def alerts(self) -> List[Alert]:
        with self._lock:
            return self.alert_manager.alerts

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        with self._lock:
            return self.alert_manager.get(alert_id)

    def decide(self, alert_id: str, decision: str) -> Alert:
        with self._lock:
            return self.alert_manager.decide(alert_id, decision)

    def decisions(self) -> List[dict]:
        with self._lock:
            return list(self.alert_manager.decisions)

    def history(self) -> List[Evidence]:
        with self._lock:
            return list(self.detector.history)

    def active_evidence(self) -> List[Evidence]:
        with self._lock:
            return self.detector.active
