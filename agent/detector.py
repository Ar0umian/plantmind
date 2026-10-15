"""Deterministic detection pipeline: telemetry -> evidence (no LLM).

Evidence is created when a check starts firing (an "episode") and is closed when
the check has stayed quiet for `clear_after` frames. IDs are EV-0001, EV-0002...
The detector never reads TelemetryFrame.scenario (that label is ground truth
for tests and the demo panel only).

Text view:
    python -m agent.detector --scenario spoofed_reading --ticks 140
"""
import argparse
from typing import Dict, List

from core.contracts import Evidence, KnowledgeMap, TelemetryFrame
from agent import expected_behavior, physical_checks
from agent.signals import Signal
from agent.telemetry_store import TelemetryStore


class Detector:
    def __init__(self, kmap: KnowledgeMap, window: int = 600, clear_after: int = 5):
        self.kmap = kmap
        self.store = TelemetryStore(maxlen=window)
        self.clear_after = clear_after
        self.history: List[Evidence] = []
        self._active: Dict[str, Evidence] = {}
        self._last_seen: Dict[str, int] = {}
        self._frame_no = 0
        self._counter = 0

    @property
    def active(self) -> List[Evidence]:
        return list(self._active.values())

    def reset(self) -> None:
        self.store.clear()
        self.history.clear()
        self._active.clear()
        self._last_seen.clear()
        self._frame_no = 0
        self._counter = 0

    def _signals(self) -> List[Signal]:
        return (expected_behavior.check_interlocks(self.store, self.kmap)
                + expected_behavior.check_commands(self.store, self.kmap)
                + physical_checks.all_checks(self.store))

    def process(self, frame: TelemetryFrame) -> List[Evidence]:
        """Ingest one frame; return evidence that STARTED on this frame."""
        self.store.add(frame)
        self._frame_no += 1
        new: List[Evidence] = []
        for signal in self._signals():
            self._last_seen[signal.key] = self._frame_no
            if signal.key in self._active:
                continue
            self._counter += 1
            evidence = Evidence(id=f"EV-{self._counter:04d}", kind=signal.kind,
                                summary=signal.summary, tags=list(signal.tags), ts=frame.ts)
            self._active[signal.key] = evidence
            self.history.append(evidence)
            new.append(evidence)
        for key in [k for k in self._active
                    if self._frame_no - self._last_seen.get(k, 0) >= self.clear_after]:
            del self._active[key]
        return new


def _main() -> None:
    from knowledge.map_builder import build_knowledge_map
    from plant.simulator.runner import SimulatorRunner
    from plant.scenarios.scenarios import SCENARIO_NAMES

    parser = argparse.ArgumentParser(description="Run the simulator through the detector")
    parser.add_argument("--scenario", default="normal", choices=SCENARIO_NAMES)
    parser.add_argument("--ticks", type=int, default=140)
    args = parser.parse_args()

    with open("plant/plc_programs/water_plant_baseline.st", encoding="utf-8") as handle:
        kmap, _ = build_knowledge_map(handle.read())     # detection uses the APPROVED program
    detector = Detector(kmap)
    runner = SimulatorRunner(interval_s=0.0)
    if args.scenario != "normal":
        runner.start_scenario(args.scenario)
    print(f"scenario: {args.scenario} (the detector does not see this label)")
    for _ in range(args.ticks):
        frame = runner.step_once()
        for evidence in detector.process(frame):
            print(f"t={frame.tick:4d}  {evidence.id}  [{evidence.kind}]  {evidence.summary}")
    print(f"evidence items: {len(detector.history)}")


if __name__ == "__main__":
    _main()
