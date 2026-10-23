"""Compact text context for model prompts (small on purpose: tokens cost credits)."""
from typing import List

from core.contracts import Evidence, KnowledgeMap, TelemetryFrame

ANALOG_TAGS = ("LT-101", "FT-101", "AT-201", "LT-301", "PT-301")


def _std(series: List[float]) -> float:
    mean = sum(series) / len(series)
    return (sum((x - mean) ** 2 for x in series) / len(series)) ** 0.5


def summarize_frames(frames: List[TelemetryFrame]) -> str:
    if not frames:
        return "No telemetry available."
    lines = [f"Telemetry, last {len(frames)} frames (one frame per second):"]
    for tag in ANALOG_TAGS:
        series = [f.values[tag] for f in frames if tag in f.values]
        if series:
            note = " (reading is EXACTLY constant: no noise at all)" if max(series) == min(series) else ""
            lines.append(f"- {tag}: first={series[0]:.2f} last={series[-1]:.2f} min={min(series):.2f} "
                         f"max={max(series):.2f} std={_std(series):.3f}{note}")
    last = frames[-1]
    for pump, running in last.status.items():
        streak = 0
        for frame in reversed(frames):
            if frame.status.get(pump) is running:
                streak += 1
            else:
                break
        lines.append(f"- {pump}: {'ON' if running else 'OFF'} for the last {streak} of {len(frames)} frames "
                     f"(command now {'ON' if last.commands.get(pump) else 'OFF'})")
    return "\n".join(lines)


def summarize_map(kmap: KnowledgeMap) -> str:
    lines = [f"Plant: {kmap.plant_name} (approved PLC program hash {kmap.program_hash})", "Equipment:"]
    for item in kmap.equipment:
        unit = f" [{item.unit}]" if item.unit else ""
        lines.append(f"- {item.tag}: {item.name}{unit}")
    lines.append("Protective interlocks in the approved program:")
    for il in kmap.interlocks:
        joiner = " OR " if il.combinator == "any" else " AND "
        cond = joiner.join(
            f"{c.tag} is {'on' if c.value else 'off'}" if isinstance(c.value, bool)
            else f"{c.tag} {c.op} {c.value}" for c in il.conditions)
        lines.append(f"- {il.id}: trips {il.target} when {cond}. {il.purpose}".rstrip())
    if kmap.relations:
        lines.append("Control relations:")
        lines.extend(f"- {r.description}" for r in kmap.relations)
    return "\n".join(lines)


def format_evidence(evidence: List[Evidence]) -> str:
    return "\n".join(f"- {e.id} [{e.kind}] tags={','.join(e.tags)}: {e.summary}" for e in evidence)
