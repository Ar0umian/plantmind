"""Engine: simulator -> detector -> alerts -> model analysis, plus the Change Guard check
of the running program, with optional background threads.

All public methods are thread-safe (one re-entrant lock). The scenario label is
exposed ONLY as `demo_scenario` for the demo control panel; detection never sees it.

Model work never blocks telemetry: while the engine runs in the background, jobs (alert
analysis, program check) go to a worker thread; with manual `step()` calls (tests) they run inline.
"""
import queue
import threading
import time
from pathlib import Path
from typing import List, Optional

from core.config import get_settings
from core.contracts import Alert, Evidence, KnowledgeMap, TelemetryFrame
from core.llm_client import LLMClient
from agent.alerts import AlertManager
from agent.analysis import AnalysisPipeline, apply_result
from agent.detector import Detector
from knowledge.change_guard import GuardResult, GuardService
from knowledge.map_builder import build_knowledge_map
from plant.scenarios.scenarios import SCENARIOS, SCENARIO_NAMES
from plant.simulator.runner import SimulatorRunner

ROOT = Path(__file__).resolve().parents[1]
PLC_DIR = ROOT / "plant" / "plc_programs"
APPROVED_PROGRAM = PLC_DIR / "water_plant_baseline.st"
# Demo plumbing: which program file the simulated PLC is "running" for each variant.
PROGRAMS = {"baseline": APPROVED_PROGRAM, "tampered": PLC_DIR / "water_plant_tampered.st"}


def load_approved_map() -> KnowledgeMap:
    kmap, _ = build_knowledge_map(APPROVED_PROGRAM.read_text(encoding="utf-8"))
    return kmap


class Engine:
    def __init__(self, runner: Optional[SimulatorRunner] = None, kmap: Optional[KnowledgeMap] = None,
                 interval_s: Optional[float] = None, ticks_per_frame: int = 1,
                 analyzer: Optional[AnalysisPipeline] = None, analyze: bool = True):
        self.interval_s = interval_s if interval_s is not None else get_settings().telemetry_interval_s
        self.runner = runner or SimulatorRunner(interval_s=0.0, ticks_per_frame=ticks_per_frame)
        self.kmap = kmap or load_approved_map()
        self.detector = Detector(self.kmap)
        self.alert_manager = AlertManager()
        self.analyzer: Optional[AnalysisPipeline] = analyzer
        if self.analyzer is None and analyze:
            self.analyzer = AnalysisPipeline(LLMClient(), self.kmap)
        if self.analyzer is not None and self.analyzer.context_provider is None:
            self.analyzer.context_provider = self._guard_context
        guard_llm = self.analyzer.llm if self.analyzer is not None else None
        self.guard = GuardService(APPROVED_PROGRAM.read_text(encoding="utf-8"), llm=guard_llm)
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._worker: Optional[threading.Thread] = None
        self._queue: "queue.Queue" = queue.Queue()
        self._running = False
        self._frame_no = 0
        self._last_variant: Optional[str] = None
        self._running_result: Optional[GuardResult] = None

    # ------------------------------------------------------------- stepping
    def step(self) -> TelemetryFrame:
        with self._lock:
            frame = self.runner.step_once()
            self._frame_no += 1
            variant = self.runner.sim.variant
            if variant != self._last_variant:
                self._last_variant = variant
                self._dispatch(("guard", variant, None))
            new = self.detector.process(frame)
            changed = self.alert_manager.ingest(new, self._frame_no, frame.ts)
            if changed and self.analyzer is not None:
                snapshot = self.runner.recent_frames(60)
                for alert in changed:
                    self._dispatch(("analyze", alert.id, snapshot))
            return frame

    def _dispatch(self, job) -> None:
        if self._running:
            self._queue.put(job)
        else:
            self._run_job(job)

    def _run_job(self, job) -> None:
        kind, first, second = job
        if kind == "analyze" and self.analyzer is not None:
            self._analyze(first, second)
        elif kind == "guard":
            self._check_running_program(first)

    def _analyze(self, alert_id: str, frames: List[TelemetryFrame]) -> None:
        """Runs the model analysis for one alert (the model call happens outside the lock)."""
        with self._lock:
            alert = self.alert_manager.get(alert_id)
            if alert is None:
                return
            snapshot = Alert(id=alert.id, ts=alert.ts, severity=alert.severity,
                             title=alert.title, evidence=list(alert.evidence))
        result = self.analyzer.analyze(snapshot, frames)
        if result is None:
            return
        with self._lock:
            current = self.alert_manager.get(alert_id)
            if current is None:
                return
            if [e.id for e in current.evidence] != [e.id for e in snapshot.evidence]:
                return            # the alert changed while the model was thinking; a newer pass is queued
            apply_result(current, result)

    def _check_running_program(self, variant: str) -> None:
        """Reads back the program the PLC runs and compares it with the approved one."""
        result = None
        if variant != "baseline":
            text = PROGRAMS[variant].read_text(encoding="utf-8")
            result = self.guard.check(text, source="running program (read back from the PLC)")
        with self._lock:
            if self.runner.sim.variant == variant:        # still the current program
                self._running_result = result

    def _guard_context(self, alert: Alert) -> str:
        with self._lock:
            result = self._running_result
        if result is None or not result.report.findings:
            return ""
        lines = ["Change Guard: the PLC program currently running differs from the approved program."]
        lines += [f"- {f.id} [{f.final_severity().value}] {f.summary}" for f in result.report.findings[:5]]
        return "\n".join(lines)

    def _loop(self) -> None:
        while self._running:
            started = time.time()
            self.step()
            time.sleep(max(0.0, self.interval_s - (time.time() - started)))

    def _worker_loop(self) -> None:
        while self._running:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run_job(job)
            except Exception:       # background work must never take the engine down
                pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False
        for thread in (self._thread, self._worker):
            if thread is not None:
                thread.join(timeout=3.0)
        self._thread = None
        self._worker = None

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
            if self.analyzer is not None:
                self.analyzer.reset()
            self.guard.reset()
            self._running_result = None
            self._last_variant = None          # the next step re-checks the running program
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
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

    def guard_running(self) -> Optional[GuardResult]:
        """Guard result for the program the PLC currently runs (None when it matches the approved one)."""
        with self._lock:
            return self._running_result

    def llm_info(self) -> dict:
        """Which model mode is active (shown in the UI so a mock is never mistaken for AI)."""
        if self.analyzer is None:
            return {"enabled": False, "mock": None, "stats": {}}
        return {"enabled": True, "mock": bool(self.analyzer.llm.is_mock),
                "stats": dict(self.analyzer.stats)}
