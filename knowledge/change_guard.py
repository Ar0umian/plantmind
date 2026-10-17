"""Change Guard: compare a candidate PLC program with the approved baseline.

Pipeline (FR-GRD):
1. Structural diff at interlock / alarm / setpoint / command-path level (deterministic).
2. Rule-based severity per finding. This is the safety FLOOR: the model can raise it, never lower it.
3. Model assessment (optional): plain-language hazard and recommendation; JSON validated,
   unknown finding IDs ignored. If the model is unavailable the rule-based text stands.
4. MITRE ATT&CK for ICS mapping from data/mitre_ics_subset.json.
5. A human records the decision (approved / rejected / needs_review).

Programs are analyzed as text and are never executed.
"""
import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel

from agent.context import summarize_map
from core.contracts import (ChangeReport, Finding, KnowledgeMap, MitreRef, Severity,
                            max_severity, sha256_text)
from core.llm_client import LLMClient, LLMError
from knowledge.map_builder import UNWIRED, build_from_program
from knowledge.st_parser import Expr, ParsedProgram, parse_st

ROOT = Path(__file__).resolve().parents[1]
MITRE_PATH = ROOT / "data" / "mitre_ics_subset.json"
MAX_TEXT = 600


# ------------------------------------------------------------------ result types
class GuardResult(BaseModel):
    report: ChangeReport
    diff: str                                   # unified diff of the two programs
    mode: Literal["none", "mock", "live", "unavailable"]   # how the assessment was produced
    source: str
    created_ts: float


class AssessedFinding(BaseModel):
    finding_id: str
    severity: Severity
    hazard: str
    recommendation: str


class GuardAssessment(BaseModel):
    findings: List[AssessedFinding]


# --------------------------------------------------------------------- internals
class _Raw:
    def __init__(self, kind, interlock_id, summary, severity, hazard, recommendation, mitre_key):
        self.kind, self.interlock_id, self.summary = kind, interlock_id, summary
        self.severity, self.hazard, self.recommendation = severity, hazard, recommendation
        self.mitre_key = mitre_key


REVIEW = ("Do not accept this change until the responsible control engineer has reviewed it. "
          "Restore the approved logic or approve the change formally, then verify the protection "
          "locally after any restore.")


def _sig(expr: Expr) -> Tuple:
    return (expr.combinator, tuple(sorted((t.tag, t.op, repr(t.value)) for t in expr.terms)))


def _terms(expr: Expr):
    return sorted(expr.terms, key=lambda t: (t.tag, t.op))


def _same_shape(a: Expr, b: Expr) -> bool:
    ta, tb = _terms(a), _terms(b)
    return (a.combinator == b.combinator and len(ta) == len(tb)
            and all(x.tag == y.tag and x.op == y.op for x, y in zip(ta, tb)))


def _direction(old: Expr, new: Expr) -> str:
    """For same-shaped expressions: 'weakened', 'strengthened' or 'same'."""
    result = "same"
    for x, y in zip(_terms(old), _terms(new)):
        if isinstance(x.value, bool) or x.value == y.value:
            continue
        if x.op in (">", ">="):
            step = "weakened" if y.value > x.value else "strengthened"
        else:
            step = "weakened" if y.value < x.value else "strengthened"
        if step == "weakened":
            return "weakened"
        result = "strengthened"
    return result


def _fmt(expr: Expr) -> str:
    joiner = " OR " if expr.combinator == "any" else " AND "
    return joiner.join(
        f"{t.tag} is {'on' if t.value else 'off'}" if isinstance(t.value, bool)
        else f"{t.tag} {t.op} {t.value}" for t in expr.terms)


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _normalized(text: str) -> str:
    return " ".join(re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S).split())


def _beyond_limit(rule_expr: Expr, pump: str, interlocks) -> Optional[str]:
    """True-ish when an automatic stop point sits beyond a protective interlock limit."""
    for term in rule_expr.terms:
        if isinstance(term.value, bool):
            continue
        for il in interlocks:
            if il.target != pump:
                continue
            for limit in il.expr.terms:
                if limit.tag != term.tag or isinstance(limit.value, bool):
                    continue
                if term.op in (">", ">=") and limit.op in (">", ">=") and term.value > limit.value:
                    return f"{term.tag} {term.value} is beyond the approved limit of {il.id} ({limit.value})"
                if term.op in ("<", "<=") and limit.op in ("<", "<=") and term.value < limit.value:
                    return f"{term.tag} {term.value} is beyond the approved limit of {il.id} ({limit.value})"
    return None


def _diff_programs(base: ParsedProgram, cand: ParsedProgram) -> List[_Raw]:
    raws: List[_Raw] = []
    purposes = {i.id: i.purpose for i in base.interlocks}
    b_il = {i.id: i for i in base.interlocks}
    c_il = {i.id: i for i in cand.interlocks}

    for il_id, old in b_il.items():
        purpose = purposes.get(il_id) or "protective trip"
        if il_id not in c_il:
            raws.append(_Raw(
                "removed", il_id, f"{il_id} was removed (it used to trip {old.target} when {_fmt(old.expr)})",
                Severity.critical,
                f"Protection lost: {purpose}. {old.target} can keep running in the condition this interlock was designed to stop.",
                REVIEW, "interlock_removed"))
            continue
        new = c_il[il_id]
        if old.target != UNWIRED and new.target == UNWIRED:
            raws.append(_Raw(
                "modified", il_id,
                f"{il_id} is still computed but no longer trips {old.target}: the interlock is bypassed",
                Severity.critical,
                f"Protection lost: {purpose}. The condition is still evaluated, so the logic looks intact, "
                f"but {old.target} is no longer stopped by it.",
                REVIEW, "interlock_unwired"))
        elif old.target == UNWIRED and new.target != UNWIRED:
            raws.append(_Raw("modified", il_id, f"{il_id} is now wired to trip {new.target}",
                             Severity.low, f"A previously inactive interlock now protects {new.target}.",
                             "Confirm this wiring change was intended.", "interlock_added"))
        elif old.target != new.target:
            raws.append(_Raw(
                "modified", il_id, f"{il_id} now trips {new.target} instead of {old.target}",
                Severity.high,
                f"Protection moved: {purpose}. {old.target} is no longer protected by it.",
                REVIEW, "interlock_weakened"))
        if _sig(old.expr) != _sig(new.expr):
            if _same_shape(old.expr, new.expr):
                direction = _direction(old.expr, new.expr)
                if direction == "weakened":
                    raws.append(_Raw(
                        "modified", il_id,
                        f"{il_id} trip condition weakened: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                        Severity.high,
                        f"Protection delayed: {purpose}. The trip now happens later, so the process can go further "
                        f"beyond the intended limit before {new.target} is stopped.",
                        REVIEW, "interlock_weakened"))
                else:
                    raws.append(_Raw(
                        "modified", il_id,
                        f"{il_id} trip condition tightened: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                        Severity.low, "The trip now happens earlier, which is more conservative but may cause "
                        "nuisance trips.", "Confirm the new limit with the process owner.", "interlock_added"))
            else:
                raws.append(_Raw(
                    "modified", il_id,
                    f"{il_id} trip logic changed: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                    Severity.high,
                    f"The structure of the protection changed: {purpose}. Its effect can no longer be assumed.",
                    REVIEW, "interlock_weakened"))

    for il_id, new in c_il.items():
        if il_id in b_il:
            continue
        wired = new.target != UNWIRED
        raws.append(_Raw(
            "added", il_id,
            f"{il_id} was added ({'trips ' + new.target if wired else 'not wired to any pump'} when {_fmt(new.expr)})",
            Severity.low if wired else Severity.medium,
            "A new protective condition exists." if wired
            else "A new interlock is defined but protects nothing; it may be a decoy that hides a change.",
            "Confirm the new interlock was intended and tested.", "interlock_added"))

    # alarms
    b_al = {a.id: a for a in base.alarms}
    c_al = {a.id: a for a in cand.alarms}
    for al_id, old in b_al.items():
        if al_id not in c_al:
            raws.append(_Raw("removed", al_id, f"Alarm {al_id} was removed (it warned when {_fmt(old.expr)})",
                             Severity.medium,
                             "Operators will no longer be warned about this condition.", REVIEW, "alarm_removed"))
        elif _sig(old.expr) != _sig(c_al[al_id].expr):
            new = c_al[al_id]
            if _same_shape(old.expr, new.expr) and _direction(old.expr, new.expr) == "strengthened":
                raws.append(_Raw("modified", al_id, f"Alarm {al_id} tightened: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                                 Severity.info, "The alarm now triggers earlier.",
                                 "Confirm the new alarm limit.", "alarm_changed"))
            else:
                raws.append(_Raw("modified", al_id, f"Alarm {al_id} changed: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                                 Severity.medium, "Operators will be warned later, or about a different condition.",
                                 REVIEW, "alarm_changed"))
    for al_id, new in c_al.items():
        if al_id not in b_al:
            raws.append(_Raw("added", al_id, f"Alarm {al_id} was added ({_fmt(new.expr)})", Severity.info,
                             "A new operator warning exists.", "Confirm the new alarm was intended.", "alarm_changed"))

    # automatic control rules (setpoints)
    b_rules = {(r.var, r.value): r for r in base.control_rules}
    c_rules = {(r.var, r.value): r for r in cand.control_rules}
    from knowledge.st_parser import base_tag
    for key, old in b_rules.items():
        var, value = key
        pump = base_tag(var)
        action = "auto-start" if value else "auto-stop"
        if key not in c_rules:
            raws.append(_Raw("removed", None, f"The {action} rule for {pump} was removed ({_fmt(old.expr)})",
                             Severity.medium, f"{pump} is no longer controlled by this rule.", REVIEW,
                             "setpoint_changed"))
        elif _sig(old.expr) != _sig(c_rules[key].expr):
            new = c_rules[key]
            beyond = _beyond_limit(new.expr, pump, base.interlocks)      # limits of the APPROVED program
            severity = Severity.high if beyond else Severity.medium
            extra = (f" {beyond[:1].upper()}{beyond[1:]}, so only the interlock remains to stop it."
                     if beyond else "")
            raws.append(_Raw("modified", None,
                             f"The {action} rule for {pump} changed: {_fmt(old.expr)} -> {_fmt(new.expr)}",
                             severity,
                             f"The automatic control no longer keeps {pump} within its intended operating range.{extra}",
                             REVIEW, "setpoint_changed"))
    for key, new in c_rules.items():
        if key not in b_rules:
            pump = base_tag(key[0])
            raws.append(_Raw("added", None, f"A new auto-{'start' if key[1] else 'stop'} rule for {pump} was added ({_fmt(new.expr)})",
                             Severity.medium, f"{pump} gained control behaviour that was not approved.", REVIEW,
                             "setpoint_changed"))

    # external command paths
    for pump, bits in cand.command_bits.items():
        new_bits = [b for b in bits if b not in base.command_bits.get(pump, [])]
        if new_bits:
            raws.append(_Raw("added", None,
                             f"{pump} can now be commanded by an external write ({', '.join(new_bits)})",
                             Severity.medium,
                             f"A new remote command path to {pump} exists; interlocks still apply but unexpected "
                             f"starts become possible.", REVIEW, "command_path_added"))
    for pump, bits in base.command_bits.items():
        gone = [b for b in bits if b not in cand.command_bits.get(pump, [])]
        if gone:
            raws.append(_Raw("removed", None, f"External command path to {pump} was removed ({', '.join(gone)})",
                             Severity.info, "Remote commands to this pump are no longer possible.",
                             "Confirm this was intended.", "command_path_added"))

    # constructs the parser could not analyze in the candidate
    new_warnings = [w for w in cand.warnings if w not in base.warnings]
    if new_warnings:
        raws.append(_Raw("modified", None,
                         f"{len(new_warnings)} part(s) of the candidate could not be analyzed: {new_warnings[0]}",
                         Severity.medium,
                         "Logic the guard cannot read could hide a change to the protection.",
                         "Review the unanalyzed statements manually.", "interlock_added"))
    return raws


def _sort_key(raw: _Raw):
    order = {Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.low: 3, Severity.info: 4}
    return order[raw.severity]


class ChangeGuard:
    def __init__(self, approved_text: str, llm: Optional[LLMClient] = None,
                 mitre_path: Path = MITRE_PATH):
        self.approved_text = approved_text
        self.approved_hash = sha256_text(approved_text)
        self.llm = llm
        self._base = parse_st(approved_text)
        self._base_map: KnowledgeMap = build_from_program(parse_st(approved_text), approved_text)
        data = json.loads(Path(mitre_path).read_text(encoding="utf-8"))
        self._techniques: Dict[str, MitreRef] = {
            t["id"]: MitreRef(technique_id=t["id"], name=t["name"]) for t in data["techniques"]}
        self._mappings: Dict[str, List[str]] = data["mappings"]

    def _mitre(self, key: str) -> List[MitreRef]:
        return [self._techniques[i] for i in self._mappings.get(key, []) if i in self._techniques]

    def compare(self, candidate_text: str, source: str = "uploaded program") -> GuardResult:
        cand_hash = sha256_text(candidate_text)
        diff = "".join(difflib.unified_diff(
            self.approved_text.splitlines(keepends=True), candidate_text.splitlines(keepends=True),
            fromfile="approved", tofile="candidate", n=2))
        raws = _diff_programs(self._base, parse_st(candidate_text))
        raws.sort(key=_sort_key)
        findings = [Finding(id=f"F-{i:03d}", kind=r.kind, interlock_id=r.interlock_id, summary=r.summary,
                            rule_severity=r.severity, hazard=r.hazard, recommendation=r.recommendation,
                            mitre=self._mitre(r.mitre_key))
                    for i, r in enumerate(raws, start=1)]
        if not findings and _normalized(candidate_text) != _normalized(self.approved_text):
            findings.append(Finding(
                id="F-001", kind="modified", summary="The program text changed, but no change to the protective "
                "logic, alarms, setpoints or command paths was detected by the guard",
                rule_severity=Severity.low,
                hazard="Other statements or initial values differ; they may still affect behaviour.",
                recommendation="Review the diff manually.", mitre=self._mitre("interlock_added")))

        mode = "none"
        llm_ok = True
        if findings and self.llm is not None:
            mode, llm_ok = self._assess(findings)
        overall = max_severity(*[f.final_severity() for f in findings]) if findings else Severity.info
        report = ChangeReport(baseline_hash=self.approved_hash, candidate_hash=cand_hash, findings=findings,
                              overall_severity=overall, llm_available=llm_ok)
        return GuardResult(report=report, diff=diff, mode=mode, source=source, created_ts=time.time())

    # --------------------------------------------------------------- model step
    def _assess(self, findings: List[Finding]) -> Tuple[str, bool]:
        listing = "\n".join(
            f"- {f.id} [{f.rule_severity.value}] {f.summary}" for f in findings)
        user = (f"{summarize_map(self._base_map)}\n\nA candidate PLC program differs from the approved one. "
                f"Rule-based findings (cite their IDs exactly):\n{listing}\n")
        system = (
            "You are a senior ICS safety engineer reviewing changes to a PLC program of a water treatment "
            "plant. For EACH finding return: finding_id (exactly as listed), severity (info, low, medium, "
            "high or critical; you may raise the rule-based severity but never lower it), hazard (1-2 plain "
            "sentences: what could go wrong physically), recommendation (1-2 plain sentences of checks a "
            "human should do). Never tell anyone to send commands to equipment. Do not add findings.")
        try:
            out = self.llm.generate_json("super", system, user, GuardAssessment,
                                         mock=lambda: GuardAssessment(findings=[
                                             AssessedFinding(finding_id=f.id, severity=f.rule_severity,
                                                             hazard=f.hazard, recommendation=f.recommendation)
                                             for f in findings]))
        except LLMError:
            return "unavailable", False
        by_id = {f.id: f for f in findings}
        for item in out.findings:
            target = by_id.get(item.finding_id)
            if target is None:
                continue                      # unknown ID: ignored
            target.llm_severity = item.severity
            hazard = " ".join(item.hazard.split())[:MAX_TEXT]
            advice = " ".join(item.recommendation.split())[:MAX_TEXT]
            if hazard:
                target.hazard = hazard
            if advice:
                target.recommendation = advice
        return ("mock" if self.llm.is_mock else "live"), True


class GuardService:
    """Keeps guard results and the human decisions (thread-safe)."""

    def __init__(self, approved_text: str, llm: Optional[LLMClient] = None):
        self.guard = ChangeGuard(approved_text, llm)
        self._results: Dict[str, GuardResult] = {}
        self._lock = threading.RLock()

    @property
    def approved_hash(self) -> str:
        return self.guard.approved_hash

    def check(self, candidate_text: str, source: str = "uploaded program") -> GuardResult:
        with self._lock:
            key = sha256_text(candidate_text)
            if key in self._results:
                return self._results[key]
        result = self.guard.compare(candidate_text, source)      # model call outside the lock
        with self._lock:
            self._results[key] = result
            return result

    def results(self) -> List[GuardResult]:
        with self._lock:
            return sorted(self._results.values(), key=lambda r: r.created_ts, reverse=True)

    def get(self, candidate_hash: str) -> Optional[GuardResult]:
        with self._lock:
            return self._results.get(candidate_hash)

    def decide(self, candidate_hash: str, decision: str) -> GuardResult:
        if decision not in ("approved", "rejected", "needs_review"):
            raise ValueError("decision must be approved, rejected or needs_review")
        with self._lock:
            result = self._results.get(candidate_hash)
            if result is None:
                raise KeyError(candidate_hash)
            result.report.decision = decision
            return result

    def reset(self) -> None:
        with self._lock:
            self._results.clear()
