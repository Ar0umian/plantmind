"""Plant documentation generator (FR-DOC-01, FR-DOC-02, FR-DOC-04).

Turns the knowledge map of the approved PLC program into a plain-language operating
document: equipment, protective interlocks, what stops each pump, automatic control,
alarms and external command paths. Almost everything is deterministic. An optional
model-written overview is accepted only if every ID it mentions exists in the map.
Markdown and HTML are rendered from the same blocks; all dynamic text is HTML-escaped.
"""
import datetime as dt
import html
import re
from typing import List, Literal, Optional, Tuple, Union

from pydantic import BaseModel

from core.contracts import KnowledgeMap
from core.llm_client import LLMClient, LLMError
from knowledge.map_builder import UNWIRED

ID_RE = re.compile(r"\b(?:IL|AL)-\d+\b|\b[A-Z]{1,2}-\d{3}\b")
_PLAIN = ((" >= ", " is at least "), (" <= ", " is at most "), (" > ", " is above "),
          (" < ", " is below "), (" == ", " equals "), (" != ", " differs from "))

Block = Tuple  # ("p", text) | ("ul", [items]) | ("table", headers, rows)


class DocSummary(BaseModel):
    summary: str


class PlantDocument(BaseModel):
    title: str
    markdown: str
    html: str
    summary_mode: Literal["deterministic", "mock", "live"]
    program_hash: str
    generated_ts: float


def _plain(text: str) -> str:
    for old, new in _PLAIN:
        text = text.replace(old, new)
    return text


def _cond(il) -> str:
    joiner = " OR " if il.combinator == "any" else " AND "
    return _plain(joiner.join(
        f"{c.tag} is {'on' if c.value else 'off'}" if isinstance(c.value, bool)
        else f"{c.tag} {c.op} {c.value}" for c in il.conditions))


def _known_ids(kmap: KnowledgeMap) -> set:
    return ({e.tag for e in kmap.equipment} | {i.id for i in kmap.interlocks}
            | {a.id for a in kmap.alarms})


def _pumps(kmap: KnowledgeMap):
    return [e for e in kmap.equipment if e.kind == "pump"]


def _auto_stop_rules(kmap: KnowledgeMap, pump: str) -> List[str]:
    return [_plain(r.description.split(" (control rule")[0]) for r in kmap.relations
            if r.target == pump and "auto-stops" in r.description]


def _deterministic_summary(kmap: KnowledgeMap) -> str:
    sensors = [e for e in kmap.equipment if e.kind == "sensor"]
    pumps = _pumps(kmap)
    unwired = [i.id for i in kmap.interlocks if i.target == UNWIRED]
    text = (f"{kmap.plant_name} is monitored through {len(sensors)} instruments and {len(pumps)} pumps. "
            f"The approved PLC program defines {len(kmap.interlocks)} protective interlocks and "
            f"{len(kmap.alarms)} alarms, and each pump also follows automatic start and stop rules. "
            f"This document is generated from that program (hash {kmap.program_hash}).")
    if unwired:
        text += f" Warning: {', '.join(unwired)} is defined but protects nothing."
    return text


def _model_summary(kmap: KnowledgeMap, llm: Optional[LLMClient]) -> Tuple[str, str]:
    fallback = _deterministic_summary(kmap)
    if llm is None:
        return fallback, "deterministic"
    facts = "\n".join(
        [f"Plant: {kmap.plant_name}"]
        + [f"- {e.tag}: {e.name} ({e.kind})" for e in kmap.equipment]
        + [f"- {i.id}: trips {i.target} when {_cond(i)}. {i.purpose}".rstrip() for i in kmap.interlocks]
        + [f"- {_plain(r.description.split(' (control rule')[0])}" for r in kmap.relations])
    system = ("You write the overview of an operating document for new control-room operators of a water "
              "treatment plant. Use ONLY the facts given, write 3 to 5 plain sentences, mention only IDs that "
              "appear in the facts, and give no instructions to act on equipment.")
    try:
        out = llm.generate_json("nano", system, facts, DocSummary,
                                mock=lambda: DocSummary(summary=fallback))
    except LLMError:
        return fallback, "deterministic"
    text = " ".join(out.summary.split())
    unknown = [i for i in ID_RE.findall(text) if i not in _known_ids(kmap)]
    if not text or unknown:
        return fallback, "deterministic"          # ungrounded text is discarded
    return text, ("mock" if llm.is_mock else "live")


def _sections(kmap: KnowledgeMap, summary: str, mode: str) -> List[Tuple[str, List[Block]]]:
    label = {"deterministic": "", "mock": " (written by the MOCK model, offline demo)",
             "live": " (written by the model from the facts below)"}[mode]
    sections: List[Tuple[str, List[Block]]] = [("Overview" + label, [("p", summary)])]

    sections.append(("Equipment and instruments", [("table", ["Tag", "Name", "Type", "Unit"],
                     [[e.tag, e.name, e.kind, e.unit or "-"] for e in kmap.equipment])]))

    rows = []
    for il in kmap.interlocks:
        protects = "nothing (not wired to any pump)" if il.target == UNWIRED else il.target
        line = f"line {il.source_lines[0]}" if il.source_lines else "-"
        rows.append([il.id, protects, _cond(il), il.purpose or "-", line])
    blocks: List[Block] = [("table", ["ID", "Protects", "Trips when", "Purpose", "Program"], rows)]
    unwired = [i.id for i in kmap.interlocks if i.target == UNWIRED]
    if unwired:
        blocks.append(("p", f"Warning: {', '.join(unwired)} is computed by the program but is not wired to "
                            f"any pump trip, so it protects nothing."))
    sections.append(("Protective interlocks", blocks))

    items = []
    for pump in _pumps(kmap):
        reasons = [f"{i.id} ({_cond(i)})" for i in kmap.interlocks if i.target == pump.tag]
        reasons += [f"automatic control: {t}" for t in _auto_stop_rules(kmap, pump.tag)]
        items.append(f"{pump.tag} ({pump.name}) stops when: " + ("; ".join(reasons) if reasons
                     else "nothing in the approved program stops it") + ".")
    sections.append(("What stops each pump", [("ul", items)]))

    control = [_plain(r.description.split(" (control rule")[0]) for r in kmap.relations
               if r.source != "SCADA/HMI"]
    sections.append(("Automatic control", [("ul", control or ["No automatic rules were found."])]))

    sections.append(("Alarms", [("table", ["ID", "Warns when"],
                     [[a.id, _plain(f"{a.tag} {a.op} {a.value}")] for a in kmap.alarms])
                     if kmap.alarms else ("p", "No alarms are defined.")]))

    external = [r.description for r in kmap.relations if r.source == "SCADA/HMI"]
    sections.append(("External command paths", [("ul", external)] if external
                     else [("p", "No external command paths were found.")]))

    sections.append(("Limits of this document", [("ul", [
        "It is generated only from the PLC program text; physical piping, valves and site procedures are not included.",
        "It describes the APPROVED program. If the running program differs, the Change Guard reports it.",
        "Verify it with the responsible control engineers before relying on it."])]))
    return sections


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def _render_markdown(kmap: KnowledgeMap, sections, ts: float) -> str:
    out = [f"# Plant operating document: {kmap.plant_name}", "",
           f"*Generated by PlantMind on {dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')} "
           f"from the approved PLC program. Synthetic plant, advisory document.*", ""]
    for title, blocks in sections:
        out += [f"## {title}", ""]
        for block in blocks:
            if block[0] == "p":
                out += [block[1], ""]
            elif block[0] == "ul":
                out += [f"- {item}" for item in block[1]] + [""]
            else:
                headers, rows = block[1], block[2]
                out += ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows] + [""]
    return "\n".join(out)


_CSS = ("body{font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:900px;margin:24px auto;"
        "padding:0 18px;color:#1c2630}h1{font-size:24px}h2{font-size:17px;border-bottom:1px solid #d6dde5;"
        "padding-bottom:4px;margin-top:26px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d6dde5;"
        "padding:6px 8px;text-align:left;vertical-align:top}th{background:#f1f4f8}.muted{color:#5d6f82;font-size:13px}"
        "@media print{body{margin:0}}")


def _render_html(kmap: KnowledgeMap, sections, ts: float) -> str:
    e = lambda t: html.escape(str(t), quote=True)
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<title>Plant operating document: {e(kmap.plant_name)}</title><style>{_CSS}</style></head><body>",
           f"<h1>Plant operating document: {e(kmap.plant_name)}</h1>",
           f"<p class='muted'>Generated by PlantMind on "
           f"{e(dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'))} from the approved PLC program. "
           f"Synthetic plant, advisory document.</p>"]
    for title, blocks in sections:
        out.append(f"<h2>{e(title)}</h2>")
        for block in blocks:
            if block[0] == "p":
                out.append(f"<p>{e(block[1])}</p>")
            elif block[0] == "ul":
                out.append("<ul>" + "".join(f"<li>{e(item)}</li>" for item in block[1]) + "</ul>")
            else:
                head = "".join(f"<th>{e(h)}</th>" for h in block[1])
                body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in block[2])
                out.append(f"<table><tr>{head}</tr>{body}</table>")
    out.append("</body></html>")
    return "".join(out)


def generate_plant_document(kmap: KnowledgeMap, llm: Optional[LLMClient] = None) -> PlantDocument:
    summary, mode = _model_summary(kmap, llm)
    ts = dt.datetime.now().timestamp()
    sections = _sections(kmap, summary, mode)
    return PlantDocument(title=f"Plant operating document: {kmap.plant_name}",
                         markdown=_render_markdown(kmap, sections, ts), html=_render_html(kmap, sections, ts),
                         summary_mode=mode, program_hash=kmap.program_hash, generated_ts=ts)
