"""Expected-behavior engine: evaluate the approved knowledge map on live data.

Uses reported values and pump status only. Never reads TelemetryFrame.scenario.
"""
from typing import List, Optional

from core.contracts import Condition, Interlock, KnowledgeMap, TelemetryFrame
from agent.signals import Signal
from agent.telemetry_store import TelemetryStore

_OPS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def _current(tag: str, frame: TelemetryFrame):
    if tag in frame.status:
        return frame.status[tag]
    return frame.values.get(tag)


def condition_true(cond: Condition, frame: TelemetryFrame) -> Optional[bool]:
    current = _current(cond.tag, frame)
    if current is None:
        return None
    return bool(_OPS[cond.op](current, cond.value))


def interlock_active(il: Interlock, frame: TelemetryFrame) -> Optional[bool]:
    results = [condition_true(c, frame) for c in il.conditions]
    if not results or any(r is None for r in results):
        return None
    return any(results) if il.combinator == "any" else all(results)


def describe_condition(cond: Condition, frame: TelemetryFrame) -> str:
    current = _current(cond.tag, frame)
    if isinstance(cond.value, bool):
        return f"{cond.tag} is {'on' if current else 'off'}"
    return f"{cond.tag} = {current:.2f} ({cond.op} {cond.value})"


def _pumps(frame: TelemetryFrame) -> List[str]:
    return list(frame.status.keys())


def check_interlocks(store: TelemetryStore, kmap: KnowledgeMap, min_frames: int = 2) -> List[Signal]:
    """Interlock condition is true but the protected pump is still running."""
    frames = store.window(min_frames)
    if len(frames) < min_frames:
        return []
    signals: List[Signal] = []
    for il in kmap.interlocks:
        if il.target not in frames[-1].status:
            continue      # UNWIRED or unknown target: handled by the Change Guard
        if all(interlock_active(il, f) is True and f.status.get(il.target) is True for f in frames):
            reasons = ", ".join(describe_condition(c, frames[-1]) for c in il.conditions)
            purpose = f" ({il.purpose})" if il.purpose else ""
            signals.append(Signal(
                key=f"interlock:{il.id}", kind="interlock_violation",
                summary=f"{il.id}{purpose}: {reasons}, but {il.target} is still running - "
                        f"the protective trip did not act",
                tags=tuple(sorted({c.tag for c in il.conditions} | {il.target}))))
    return signals


def check_commands(store: TelemetryStore, kmap: KnowledgeMap, min_frames: int = 2) -> List[Signal]:
    """A pump is commanded ON but is not running (the command is being refused)."""
    frames = store.window(min_frames)
    if len(frames) < min_frames:
        return []
    signals: List[Signal] = []
    for pump in _pumps(frames[-1]):
        if all(f.commands.get(pump) is True and f.status.get(pump) is False for f in frames):
            blockers = [il.id for il in kmap.interlocks
                        if il.target == pump and interlock_active(il, frames[-1]) is True]
            why = (f"blocked by {', '.join(blockers)}" if blockers
                   else "no known interlock explains it")
            signals.append(Signal(
                key=f"command:{pump}", kind="command_anomaly",
                summary=f"{pump} is commanded ON but not running ({why}) - "
                        f"an unexpected start command is being issued",
                tags=(pump,)))
    return signals
