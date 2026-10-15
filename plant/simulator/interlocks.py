"""Interlock definitions for the synthetic water plant.

These mirror the IL_xx logic in plant/plc_programs/*.st. Interlock IDs are
identical in both places (see docs/FUNCTIONAL_REQUIREMENTS.md, section 0).

Interlocks read REPORTED sensor values and pump feedback, exactly like a PLC.
Variant "tampered" models a modified program in which IL-04 is still computed
but is no longer wired to the pump trip (a bypass).
"""
import operator
from dataclasses import dataclass
from typing import Dict, List, Tuple, Union

Cond = Tuple[str, str, Union[bool, float]]

_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
        ">=": operator.ge, "==": operator.eq, "!=": operator.ne}


@dataclass(frozen=True)
class ILDef:
    id: str
    target: str
    conditions: Tuple[Cond, ...]
    purpose: str


INTERLOCKS: Tuple[ILDef, ...] = (
    ILDef("IL-01", "P-101", (("LT-101", "<", 15.0),),
          "Trip intake pump when the raw tank is almost empty (dry-run protection)"),
    ILDef("IL-02", "P-101", (("LT-301", ">", 95.0),),
          "Trip intake pump when the treated tank is almost full (overflow protection)"),
    ILDef("IL-03", "P-201", (("P-101", "==", False),),
          "Trip chlorine dosing when there is no intake flow"),
    ILDef("IL-04", "P-201", (("AT-201", ">", 4.0),),
          "Trip chlorine dosing on chlorine overdose"),
    ILDef("IL-05", "P-301", (("LT-301", "<", 15.0),),
          "Trip distribution pump when the treated tank is almost empty"),
    ILDef("IL-06", "P-301", (("PT-301", ">", 6.0),),
          "Trip distribution pump on overpressure"),
)

# Interlocks that are computed but not wired to the trip, per program variant.
UNWIRED: Dict[str, set] = {"baseline": set(), "tampered": {"IL-04"}}


def condition_true(cond: Cond, reported: Dict[str, float], status: Dict[str, bool]) -> bool:
    tag, op, value = cond
    current = status[tag] if tag in status else reported[tag]
    return bool(_OPS[op](current, value))


def interlock_true(il: ILDef, reported: Dict[str, float], status: Dict[str, bool]) -> bool:
    """Condition state of an interlock (independent of wiring)."""
    return any(condition_true(c, reported, status) for c in il.conditions)


def tripping(target: str, variant: str, reported: Dict[str, float],
             status: Dict[str, bool]) -> List[str]:
    """IDs of wired interlocks that currently trip the given target."""
    unwired = UNWIRED[variant]
    return [il.id for il in INTERLOCKS
            if il.target == target and il.id not in unwired
            and interlock_true(il, reported, status)]
