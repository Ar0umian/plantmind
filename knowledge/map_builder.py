"""Build knowledge_map.json (the shared KnowledgeMap contract) from a .st program.

Deterministic: everything comes from the parser. An interlock that is computed
but not used by any *_RUN trip gets target "UNWIRED" (this is how a bypass such
as the tampered IL-04 becomes visible). Consumers must treat "UNWIRED" as
"protects nothing".

Usage:
    python -m knowledge.map_builder plant/plc_programs/water_plant_baseline.st --out fixtures/knowledge_map.json
"""
import argparse
from typing import List, Optional, Tuple

from core.contracts import (Alarm, Condition, Equipment, Interlock, KnowledgeMap,
                            Relation, sha256_text)
from knowledge.st_parser import Expr, ParsedProgram, base_tag, parse_st

UNWIRED = "UNWIRED"


def _split_comment(comment: str) -> Tuple[str, Optional[str]]:
    """'Raw water tank level, %' -> ('Raw water tank level', '%')."""
    if "," in comment:
        name, unit = comment.rsplit(",", 1)
        return name.strip(), (unit.strip() or None)
    return comment.strip(), None


def _describe(expr: Expr) -> str:
    joiner = " OR " if expr.combinator == "any" else " AND "
    parts = []
    for term in expr.terms:
        if isinstance(term.value, bool):
            parts.append(f"{term.tag} is {'on' if term.value else 'off'}")
        else:
            parts.append(f"{term.tag} {term.op} {term.value}")
    return joiner.join(parts)


def _equipment(program: ParsedProgram) -> List[Equipment]:
    items: List[Equipment] = []
    for decl in program.declarations:
        if decl.section == "VAR_INPUT" and decl.type == "REAL":
            name, unit = _split_comment(decl.comment)
            tag = base_tag(decl.name)
            items.append(Equipment(tag=tag, name=name or tag, kind="sensor", unit=unit))
        elif decl.section == "VAR_OUTPUT" and decl.type == "BOOL" and decl.name.endswith("_RUN"):
            tag = base_tag(decl.name)
            name = decl.comment
            if name.lower().endswith(" run"):
                name = name[:-4]
            items.append(Equipment(tag=tag, name=name or tag, kind="pump", unit=None))
    return items


def _relations(program: ParsedProgram) -> List[Relation]:
    relations: List[Relation] = []
    for rule in program.control_rules:
        target = base_tag(rule.var)
        action = "auto-starts" if rule.value else "auto-stops"
        source = rule.expr.terms[0].tag if rule.expr.terms else target
        relations.append(Relation(
            source=source, target=target,
            description=f"{target} {action} when {_describe(rule.expr)} (control rule, line {rule.line})"))
    for pump, bits in program.command_bits.items():
        relations.append(Relation(
            source="SCADA/HMI", target=pump,
            description=f"{pump} can also be commanded by an external SCADA/HMI write ({', '.join(bits)}); "
                        f"interlocks still apply"))
    return relations


def build_from_program(program: ParsedProgram, source_text: str) -> KnowledgeMap:
    interlocks = []
    for item in program.interlocks:
        interlocks.append(Interlock(
            id=item.id, target=item.target,
            conditions=[Condition(tag=t.tag, op=t.op, value=t.value) for t in item.expr.terms],
            combinator=item.expr.combinator, purpose=item.purpose, source_lines=[item.line]))
    alarms = []
    for item in program.alarms:
        term = item.expr.terms[0] if item.expr.terms else None
        if term is None or isinstance(term.value, bool):
            program.warnings.append(f"{item.id}: only numeric single-comparison alarms are supported")
            continue
        alarms.append(Alarm(id=item.id, tag=term.tag, op=term.op, value=float(term.value), message=""))
    return KnowledgeMap(
        plant_name=program.program_name, program_hash=sha256_text(source_text),
        equipment=_equipment(program), interlocks=interlocks, alarms=alarms,
        relations=_relations(program))


def build_knowledge_map(source_text: str) -> Tuple[KnowledgeMap, List[str]]:
    """Returns (knowledge map, parser warnings)."""
    program = parse_st(source_text)
    kmap = build_from_program(program, source_text)
    return kmap, program.warnings


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build a knowledge map from a .st file")
    parser.add_argument("st_file")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    with open(args.st_file, encoding="utf-8") as handle:
        text = handle.read()
    kmap, warnings = build_knowledge_map(text)
    print(f"plant: {kmap.plant_name}   program hash: {kmap.program_hash}")
    print(f"equipment: {len(kmap.equipment)}   interlocks: {len(kmap.interlocks)}   "
          f"alarms: {len(kmap.alarms)}   relations: {len(kmap.relations)}")
    for item in kmap.interlocks:
        conds = f" {item.combinator.upper()} ".join(
            f"{c.tag} {c.op} {c.value}" for c in item.conditions)
        flag = "   <-- UNWIRED (protects nothing)" if item.target == UNWIRED else ""
        print(f"  {item.id}  target={item.target:<8} {conds}{flag}")
    for warning in warnings:
        print("  WARNING:", warning)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(kmap.model_dump_json(indent=2))
        print("written:", args.out)


if __name__ == "__main__":
    _main()
