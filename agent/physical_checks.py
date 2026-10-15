"""Physical-consistency checks on reported data (deterministic, no LLM).

Thresholds are demo values tuned to the synthetic plant in docs/FUNCTIONAL_REQUIREMENTS.md.
"""
from typing import List

from agent.signals import Signal
from agent.telemetry_store import TelemetryStore, slope

FLAT_WINDOW = 15            # frames of an exactly constant reading => flatline
FLOW_WINDOW = 3             # frames to confirm a flow inconsistency
FLOW_MIN_RUNNING = 80.0     # m3/h; pump running but flow below this is suspicious
FLOW_MAX_STOPPED = 40.0     # m3/h; pump stopped but flow above this is suspicious
TREND_WINDOW = 20           # frames for the level trend
LEVEL_FALL_MAX = -0.05      # %/frame; must fall faster than this while pumping
LEVEL_RISE_MIN = 0.05       # %/frame; must rise faster than this while stopped
DOSE_WINDOW = 15            # frames of continuous dosing
DOSE_RISE_MIN = 0.01        # ppm/frame
DOSE_LOW_MEAN = 2.0         # ppm; dosing should not continue while the reading stays this low


def check_stale(store: TelemetryStore) -> List[Signal]:
    """An analog reading that is EXACTLY constant for many frames (real signals carry noise)."""
    latest = store.latest()
    if latest is None:
        return []
    signals = []
    for tag in latest.values:
        series = store.values(tag, FLAT_WINDOW)
        if len(series) == FLAT_WINDOW and max(series) == min(series):
            signals.append(Signal(
                key=f"stale:{tag}", kind="stale_value",
                summary=f"{tag} has read exactly {series[-1]} for {FLAT_WINDOW} consecutive frames "
                        f"(no noise at all): the sensor looks frozen or failed",
                tags=(tag,)))
    return signals


def check_flow(store: TelemetryStore) -> List[Signal]:
    frames = store.window(FLOW_WINDOW)
    if len(frames) < FLOW_WINDOW or any("FT-101" not in f.values for f in frames):
        return []
    last = frames[-1]
    level = last.values.get("LT-101")
    level_text = f"; LT-101 still reports {level:.1f}%" if level is not None else ""
    if all(f.status.get("P-101") is True and f.values["FT-101"] < FLOW_MIN_RUNNING for f in frames):
        return [Signal(
            key="phys:flow_lost", kind="physical_inconsistency",
            summary=f"P-101 is running but intake flow FT-101 is only {last.values['FT-101']:.0f} m3/h"
                    f"{level_text}: the water source may be starved or the level reading is wrong",
            tags=("P-101", "FT-101", "LT-101"))]
    if all(f.status.get("P-101") is False and f.values["FT-101"] > FLOW_MAX_STOPPED for f in frames):
        return [Signal(
            key="phys:flow_while_stopped", kind="physical_inconsistency",
            summary=f"P-101 is stopped but FT-101 reports {last.values['FT-101']:.0f} m3/h: "
                    f"flow without a running pump",
            tags=("P-101", "FT-101"))]
    return []


def check_level_trend(store: TelemetryStore) -> List[Signal]:
    frames = store.window(TREND_WINDOW)
    if len(frames) < TREND_WINDOW or any("LT-101" not in f.values for f in frames):
        return []
    series = [f.values["LT-101"] for f in frames]
    trend = slope(series)
    if all(f.status.get("P-101") is True for f in frames) and trend > LEVEL_FALL_MAX:
        return [Signal(
            key="phys:level_trend", kind="physical_inconsistency",
            summary=f"LT-101 does not fall while P-101 has been pumping for {TREND_WINDOW} frames "
                    f"(trend {trend:+.2f} %/frame): the raw tank level reading is inconsistent "
                    f"with the pump activity",
            tags=("LT-101", "P-101"))]
    if all(f.status.get("P-101") is False for f in frames) and trend < LEVEL_RISE_MIN:
        return [Signal(
            key="phys:level_trend", kind="physical_inconsistency",
            summary=f"LT-101 does not rise while P-101 has been stopped for {TREND_WINDOW} frames "
                    f"(trend {trend:+.2f} %/frame): the raw tank level reading is inconsistent "
                    f"with the pump activity",
            tags=("LT-101", "P-101"))]
    return []


def check_dosing(store: TelemetryStore) -> List[Signal]:
    frames = store.window(DOSE_WINDOW)
    if len(frames) < DOSE_WINDOW or any("AT-201" not in f.values for f in frames):
        return []
    series = [f.values["AT-201"] for f in frames]
    mean = sum(series) / len(series)
    if (all(f.status.get("P-201") is True for f in frames)
            and slope(series) < DOSE_RISE_MIN and mean < DOSE_LOW_MEAN):
        return [Signal(
            key="phys:dose_no_rise", kind="physical_inconsistency",
            summary=f"P-201 has been dosing chlorine for {DOSE_WINDOW} frames but AT-201 stays near "
                    f"{mean:.2f} ppm: the analyzer may be failing while dosing continues unchecked",
            tags=("P-201", "AT-201"))]
    return []


def all_checks(store: TelemetryStore) -> List[Signal]:
    return check_stale(store) + check_flow(store) + check_level_trend(store) + check_dosing(store)
