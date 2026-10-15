"""Parser for the IEC 61131-3 Structured Text subset used by PlantMind.

Supported: PROGRAM, VAR_INPUT / VAR_OUTPUT / VAR sections with trailing
comments, boolean assignments (IL_xx, AL_xx, *_CMD, *_RUN), IF ... THEN ...
END_IF blocks that assign TRUE/FALSE, comparisons (< <= > >= = <>), AND, OR,
NOT. Parentheses are only understood inside the wiring expression of *_RUN.

The program is analyzed as text and is NEVER executed.
Naming convention: tag LT_101 maps to LT-101, P_101_RUN maps to pump P-101.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

Value = Union[bool, float]
_OPS = {"<": "<", ">": ">", "<=": "<=", ">=": ">=", "=": "==", "<>": "!="}

_COMMENT = re.compile(r"\(\*.*?\*\)", re.S)
_VAR_BLOCK = re.compile(r"\b(VAR_INPUT|VAR_OUTPUT|VAR)\b(.*?)\bEND_VAR\b", re.S)
_DECL = re.compile(
    r"^[ \t]*(\w+)[ \t]*:[ \t]*(\w+)[ \t]*(?::=[ \t]*([^;]*?))?[ \t]*;[ \t]*(?:\(\*[ \t]*(.*?)[ \t]*\*\))?",
    re.M)
_IF = re.compile(r"\bIF\b(.*?)\bTHEN\b(.*?)\bEND_IF\b\s*;", re.S)
_ASSIGN = re.compile(r"(\w+)[ \t\r\n]*:=[ \t\r\n]*(.*?);", re.S)
_PROGRAM = re.compile(r"\bPROGRAM\s+(\w+)")
_IL_COMMENT = re.compile(r"\(\*\s*(IL-\d+)\s*:\s*(.*?)\s*\*\)", re.S)
_TERM = re.compile(
    r"^(?:(NOT)\s+)?([A-Za-z_]\w*)(?:\s*(<=|>=|<>|<|>|=)\s*(-?\d+(?:\.\d+)?|TRUE|FALSE))?$")
_TAG = re.compile(r"^([A-Z]{1,3})_(\d{3})")


@dataclass
class Term:
    tag: str
    op: str
    value: Value


@dataclass
class Expr:
    terms: List[Term]
    combinator: str = "any"          # "any" (OR) or "all" (AND)
    text: str = ""


@dataclass
class Declaration:
    name: str
    type: str
    section: str                     # VAR_INPUT, VAR_OUTPUT, VAR
    init: Optional[str]
    comment: str
    line: int


@dataclass
class ParsedInterlock:
    id: str                          # IL-01
    expr: Expr
    line: int
    purpose: str = ""
    target: str = "UNWIRED"          # pump tag, or UNWIRED when no *_RUN uses it


@dataclass
class ParsedAlarm:
    id: str                          # AL-01
    expr: Expr
    line: int


@dataclass
class ControlRule:
    var: str                         # e.g. P_201_AUTO
    value: bool                      # value assigned when the rule fires
    expr: Expr
    line: int


@dataclass
class ParsedProgram:
    program_name: str
    declarations: List[Declaration] = field(default_factory=list)
    interlocks: List[ParsedInterlock] = field(default_factory=list)
    alarms: List[ParsedAlarm] = field(default_factory=list)
    control_rules: List[ControlRule] = field(default_factory=list)
    run_wiring: Dict[str, List[str]] = field(default_factory=dict)    # P_101_RUN -> [IL-01, IL-02]
    command_bits: Dict[str, List[str]] = field(default_factory=dict)  # P-201 -> [P_201_HMI_CMD]
    warnings: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def base_tag(name: str) -> str:
    """LT_101 -> LT-101, P_101_RUN -> P-101; other names are returned unchanged."""
    match = _TAG.match(name)
    return f"{match.group(1)}-{match.group(2)}" if match else name


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _blank(text: str, spans) -> str:
    """Replace spans by spaces, keeping newlines so line numbers stay valid."""
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def parse_expr(text: str, warnings: List[str], context: str) -> Expr:
    clean = _normalize(text)
    expr = Expr(terms=[], text=clean)
    if "(" in clean or ")" in clean:
        warnings.append(f"{context}: parentheses are not supported here: '{clean}'")
        return expr
    has_or = re.search(r"\sOR\s", clean) is not None
    has_and = re.search(r"\sAND\s", clean) is not None
    if has_or and has_and:
        warnings.append(f"{context}: mixed AND/OR is not supported: '{clean}'")
        return expr
    pieces = re.split(r"\s+OR\s+", clean) if has_or else re.split(r"\s+AND\s+", clean)
    expr.combinator = "all" if has_and else "any"
    for piece in pieces:
        match = _TERM.match(piece.strip())
        if not match:
            warnings.append(f"{context}: cannot parse term '{piece}'")
            continue
        negated, name, op, raw = match.groups()
        tag = base_tag(name)
        if op is None:
            expr.terms.append(Term(tag, "==", not negated))
        else:
            value: Value = (raw == "TRUE") if raw in ("TRUE", "FALSE") else float(raw)
            expr.terms.append(Term(tag, _OPS[op], value))
    return expr


# -------------------------------------------------------------------- parser
def parse_st(source: str) -> ParsedProgram:
    masked = _blank(source, [m.span() for m in _COMMENT.finditer(source)])
    program = ParsedProgram(program_name="UnknownProgram")

    name_match = _PROGRAM.search(masked)
    if name_match:
        program.program_name = name_match.group(1)
    else:
        program.warnings.append("PROGRAM name not found")

    purposes = {m.group(1): _normalize(m.group(2)) for m in _IL_COMMENT.finditer(source)}

    # --- declarations (use the original text to keep trailing comments)
    spans = []
    for block in _VAR_BLOCK.finditer(masked):
        section = block.group(1)
        for decl in _DECL.finditer(source, block.start(2), block.end(2)):
            program.declarations.append(Declaration(
                name=decl.group(1), type=decl.group(2).upper(), section=section,
                init=(decl.group(3) or None), comment=_normalize(decl.group(4) or ""),
                line=_line_of(source, decl.start(1))))
        spans.append(block.span())
    body = _blank(masked, spans)

    # --- IF blocks -> control rules
    if_spans = []
    for block in _IF.finditer(body):
        header = parse_expr(block.group(1), program.warnings, f"line {_line_of(body, block.start())}")
        for assign in _ASSIGN.finditer(block.group(2)):
            rhs = assign.group(2).strip()
            if rhs not in ("TRUE", "FALSE"):
                program.warnings.append(
                    f"line {_line_of(body, block.start())}: IF body must assign TRUE/FALSE, got '{rhs}'")
                continue
            program.control_rules.append(ControlRule(
                var=assign.group(1), value=(rhs == "TRUE"), expr=header,
                line=_line_of(body, block.start())))
        if_spans.append(block.span())
    body = _blank(body, if_spans)

    # --- top-level assignments
    for assign in _ASSIGN.finditer(body):
        lhs, rhs = assign.group(1), _normalize(assign.group(2))
        line = _line_of(body, assign.start(1))
        il_match = re.match(r"^IL_(\d+)$", lhs)
        al_match = re.match(r"^AL_(\d+)$", lhs)
        if il_match:
            il_id = f"IL-{il_match.group(1)}"
            program.interlocks.append(ParsedInterlock(
                id=il_id, expr=parse_expr(rhs, program.warnings, il_id), line=line,
                purpose=_capitalize(purposes.get(il_id, ""))))
        elif al_match:
            al_id = f"AL-{al_match.group(1)}"
            program.alarms.append(ParsedAlarm(
                id=al_id, expr=parse_expr(rhs, program.warnings, al_id), line=line))
        elif lhs.endswith("_RUN"):
            program.run_wiring[lhs] = [f"IL-{n}" for n in re.findall(r"\bIL_(\d+)\b", rhs)]
            if " NOT " not in f" {rhs} ":
                program.warnings.append(f"{lhs}: expected 'CMD AND NOT (...)' wiring, got '{rhs}'")
        elif lhs.endswith("_CMD"):
            bits = [t for t in re.findall(r"\b\w+_HMI_CMD\b", rhs)]
            if bits:
                program.command_bits[base_tag(lhs)] = bits
        else:
            program.warnings.append(f"line {line}: unrecognized statement for '{lhs}'")

    # --- wire interlocks to their targets
    for interlock in program.interlocks:
        targets = [base_tag(run) for run, ids in program.run_wiring.items() if interlock.id in ids]
        if len(targets) > 1:
            program.warnings.append(f"{interlock.id} is wired to several targets: {targets}")
        if targets:
            interlock.target = targets[0]
    return program
