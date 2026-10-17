"""Incident report generator (FR-OPS-04, FR-OPS-05, FR-OPS-06).

A report is assembled from facts already in the system: rule-based evidence, the
model analysis (clearly labelled), the Change Guard result for the running program,
the human decisions, MITRE ATT&CK mapping and Tavily references. Markdown and HTML
are rendered from the same data; every dynamic string is HTML-escaped.
"""
import datetime as dt
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from agent.context import summarize_frames
from agent.tavily_client import TavilyClient
from core.contracts import Alert, Hypothesis, IncidentReport, MitreRef, ReferenceLink, TelemetryFrame
from knowledge.change_guard import GuardResult

ROOT = Path(__file__).resolve().parents[1]
MITRE_PATH = ROOT / "data" / "mitre_ics_subset.json"

# Which causes look like an attack pattern, and the mapping key to use for each.
LABEL_TO_MITRE_KEY = {"logic_tampering": "interlock_unwired", "spoofing": "spoofed_reading",
                      "command_abuse": "abnormal_command"}
NO_MITRE_NOTE = "No ATT&CK technique mapped: the most likely cause is not an attack pattern."


@dataclass
class ReportBundle:
    report: IncidentReport
    alert: Alert
    llm_mock: bool
    guard: Optional[GuardResult]
    telemetry_lines: List[str] = field(default_factory=list)
    mitre_note: str = ""


def _ts(value: float) -> str:
    return dt.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _catalog() -> Dict:
    data = json.loads(MITRE_PATH.read_text(encoding="utf-8"))
    return {"techniques": {t["id"]: MitreRef(technique_id=t["id"], name=t["name"]) for t in data["techniques"]},
            "mappings": data["mappings"]}


def _mitre_refs(labels: List[str], guard: Optional[GuardResult]) -> List[MitreRef]:
    catalog = _catalog()
    refs: Dict[str, MitreRef] = {}
    for label in labels:
        key = LABEL_TO_MITRE_KEY.get(label)
        for tid in catalog["mappings"].get(key, []) if key else []:
            if tid in catalog["techniques"]:
                refs[tid] = catalog["techniques"][tid]
    if guard is not None and guard.report.findings and "logic_tampering" in labels:
        for finding in guard.report.findings:
            for ref in finding.mitre:
                refs[ref.technique_id] = ref
    return list(refs.values())


def _timeline(alert: Alert, decisions: List[dict], guard: Optional[GuardResult]) -> List[str]:
    events = [(alert.ts, 0, f"Alert {alert.id} opened ({alert.severity.value}): {alert.title}")]
    for ev in alert.evidence:
        events.append((ev.ts, 1, f"{ev.id} raised [{ev.kind}]: {ev.summary}"))
    if guard is not None and guard.report.findings:
        top = guard.report.findings[0]
        events.append((guard.created_ts, 2,
                       f"Change Guard: the running program differs from the approved one "
                       f"({len(guard.report.findings)} finding(s), overall "
                       f"{guard.report.overall_severity.value}); first: {top.summary}"))
    for d in decisions:
        events.append((d["ts"], 3, f"Human decision on {d['alert_id']}: {d['decision']}"))
    events.sort(key=lambda e: (e[0], e[1]))
    return [f"{_ts(ts)}  {text}" for ts, _, text in events]


def build_incident_report(alert: Alert, frames: List[TelemetryFrame], decisions: List[dict],
                          guard: Optional[GuardResult], tavily: TavilyClient,
                          llm_mock: bool = True) -> ReportBundle:
    hypotheses = list(alert.hypotheses)
    top_label = hypotheses[0].label if hypotheses else "unknown"
    labels = [top_label] + [h.label for h in hypotheses[1:3] if h.confidence >= 0.25]

    references: List[ReferenceLink] = []
    seen = set()
    for label in dict.fromkeys(labels):
        for link in tavily.references_for(label):
            if link.url not in seen:
                seen.add(link.url)
                references.append(link)
    references = references[:5]

    actions = [f"Decision: {d['decision']} (recorded {_ts(d['ts'])})" for d in decisions]
    actions += [f"Suggested check: {text}" for text in alert.recommended_actions]

    mitre = _mitre_refs([top_label], guard)
    report = IncidentReport(
        id=f"R-{alert.id}", alert_id=alert.id, created_ts=dt.datetime.now().timestamp(),
        timeline=_timeline(alert, decisions, guard), evidence=list(alert.evidence),
        hypotheses=hypotheses, actions=actions, mitre=mitre, references=references)
    bundle = ReportBundle(report=report, alert=alert, llm_mock=llm_mock, guard=guard,
                          telemetry_lines=summarize_frames(frames).splitlines(),
                          mitre_note="" if mitre else NO_MITRE_NOTE)
    report.markdown = render_markdown(bundle)
    return bundle


# ---------------------------------------------------------------------- markdown
def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def render_markdown(bundle: ReportBundle) -> str:
    r, a = bundle.report, bundle.alert
    source = "MOCK MODEL (offline demo, not a real AI analysis)" if bundle.llm_mock else "Nemotron via Nebius Token Factory"
    out: List[str] = [
        f"# Incident report {r.id}", "",
        f"*Generated by PlantMind on {_ts(r.created_ts)}. Advisory system, synthetic plant data. "
        f"Model analysis source: {source}.*", "",
        "## Summary", "",
        f"- Alert: {a.id} - {a.title}",
        f"- Severity: {a.severity.value.upper()} (rule-based floor; the model can only raise it)",
        f"- Status: {a.status}",
        f"- Opened: {_ts(a.ts)}",
        f"- Evidence items: {len(a.evidence)}", "",
        "## What happened (rule-based evidence)", ""]
    out += [f"- **{e.id}** [{e.kind}] {e.summary}" for e in r.evidence] or ["- None"]
    out += ["", "## Most likely causes (model-generated, uncertain)", ""]
    if a.operator_explanation:
        out += [a.operator_explanation, ""]
    if r.hypotheses:
        out += ["| Cause | Confidence | Reasoning | Evidence |", "|---|---|---|---|"]
        out += [f"| {_cell(h.label.replace('_', ' '))} | {round(h.confidence * 100)}% | "
                f"{_cell(h.reasoning)} | {_cell(', '.join(h.evidence_ids))} |" for h in r.hypotheses]
    else:
        out += ["No ranked causes are available for this alert."]
    out += ["", "## Program integrity (Change Guard)", ""]
    if bundle.guard is None or not bundle.guard.report.findings:
        out += ["The program running on the PLC matches the approved baseline."]
    else:
        g = bundle.guard.report
        out += [f"The running program DIFFERS from the approved baseline: {len(g.findings)} finding(s), "
                f"overall {g.overall_severity.value.upper()}.", ""]
        out += [f"- **{f.id}** [{f.final_severity().value}] {f.summary}" for f in g.findings]
    out += ["", "## Timeline", ""] + [f"- {line}" for line in r.timeline]
    out += ["", "## Actions and decisions", ""]
    out += [f"- {line}" for line in r.actions] or ["- No decisions recorded yet."]
    out += ["", "## ATT&CK for ICS mapping", ""]
    out += [f"- {m.technique_id} {m.name}" for m in r.mitre] or [bundle.mitre_note or NO_MITRE_NOTE]
    out += ["", "## References", ""]
    out += [f"- [{_cell(l.title)}]({l.url})" for l in r.references] or ["- No references available."]
    out += ["", "## Appendix: telemetry summary", ""] + [f"    {line}" for line in bundle.telemetry_lines]
    out += ["", "---", "PlantMind is advisory only: it never sends commands to equipment. "
            "Every action above is a suggestion for a human to decide."]
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------- html
_CSS = ("body{font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:860px;margin:24px auto;"
        "padding:0 18px;color:#1c2630}h1{font-size:24px}h2{font-size:17px;border-bottom:1px solid #d6dde5;"
        "padding-bottom:4px;margin-top:26px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d6dde5;"
        "padding:6px 8px;text-align:left;vertical-align:top}th{background:#f1f4f8}.sev{display:inline-block;padding:1px 9px;"
        "border-radius:5px;color:#fff;font-weight:700}.high,.critical{background:#c8452d}.medium{background:#b9791f}"
        ".low,.info{background:#2f7d57}.muted{color:#5d6f82;font-size:13px}.banner{background:#fff4d6;border:1px solid #e3c26b;"
        "padding:8px 10px;border-radius:6px}pre{background:#f1f4f8;padding:10px;overflow:auto}"
        "@media print{body{margin:0}}")


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def render_html(bundle: ReportBundle) -> str:
    r, a = bundle.report, bundle.alert
    source = ("MOCK MODEL (offline demo, not a real AI analysis)" if bundle.llm_mock
              else "Nemotron via Nebius Token Factory")
    parts: List[str] = [
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Incident report {_e(r.id)}</title>"
        f"<style>{_CSS}</style></head><body>",
        f"<h1>Incident report {_e(r.id)}</h1>",
        f"<p class='muted'>Generated by PlantMind on {_e(_ts(r.created_ts))}. Advisory system, synthetic plant data.</p>"]
    if bundle.llm_mock:
        parts.append(f"<p class='banner'>Model analysis source: {_e(source)}</p>")
    parts += [
        "<h2>Summary</h2><ul>",
        f"<li>Alert: {_e(a.id)} &ndash; {_e(a.title)}</li>",
        f"<li>Severity: <span class='sev {_e(a.severity.value)}'>{_e(a.severity.value.upper())}</span> "
        f"<span class='muted'>(rule-based floor; the model can only raise it)</span></li>",
        f"<li>Status: {_e(a.status)}</li><li>Opened: {_e(_ts(a.ts))}</li>"
        f"<li>Evidence items: {len(a.evidence)}</li></ul>",
        "<h2>What happened <span class='muted'>(rule-based evidence)</span></h2><ul>"]
    parts += [f"<li><b>{_e(e.id)}</b> [{_e(e.kind)}] {_e(e.summary)}</li>" for e in r.evidence] or ["<li>None</li>"]
    parts.append("</ul><h2>Most likely causes <span class='muted'>(model-generated, uncertain)</span></h2>")
    if a.operator_explanation:
        parts.append(f"<p>{_e(a.operator_explanation)}</p>")
    if r.hypotheses:
        parts.append("<table><tr><th>Cause</th><th>Confidence</th><th>Reasoning</th><th>Evidence</th></tr>")
        parts += [f"<tr><td>{_e(h.label.replace('_', ' '))}</td><td>{round(h.confidence * 100)}%</td>"
                  f"<td>{_e(h.reasoning)}</td><td>{_e(', '.join(h.evidence_ids))}</td></tr>" for h in r.hypotheses]
        parts.append("</table>")
    else:
        parts.append("<p>No ranked causes are available for this alert.</p>")
    parts.append("<h2>Program integrity <span class='muted'>(Change Guard)</span></h2>")
    if bundle.guard is None or not bundle.guard.report.findings:
        parts.append("<p>The program running on the PLC matches the approved baseline.</p>")
    else:
        g = bundle.guard.report
        parts.append(f"<p>The running program <b>differs</b> from the approved baseline: {len(g.findings)} finding(s), "
                     f"overall <span class='sev {_e(g.overall_severity.value)}'>{_e(g.overall_severity.value.upper())}</span>.</p><ul>")
        parts += [f"<li><b>{_e(f.id)}</b> [{_e(f.final_severity().value)}] {_e(f.summary)}</li>" for f in g.findings]
        parts.append("</ul>")
    parts.append("<h2>Timeline</h2><ul>" + "".join(f"<li>{_e(line)}</li>" for line in r.timeline) + "</ul>")
    parts.append("<h2>Actions and decisions</h2><ul>" +
                 ("".join(f"<li>{_e(line)}</li>" for line in r.actions) or "<li>No decisions recorded yet.</li>") + "</ul>")
    parts.append("<h2>ATT&amp;CK for ICS mapping</h2>")
    parts.append("<ul>" + "".join(f"<li>{_e(m.technique_id)} {_e(m.name)}</li>" for m in r.mitre) + "</ul>"
                 if r.mitre else f"<p>{_e(bundle.mitre_note or NO_MITRE_NOTE)}</p>")
    parts.append("<h2>References</h2>")
    links = []
    for link in r.references:
        url = link.url if link.url.startswith(("http://", "https://")) else "#"
        links.append(f"<li><a href='{_e(url)}' rel='noopener noreferrer'>{_e(link.title)}</a></li>")
    parts.append("<ul>" + ("".join(links) or "<li>No references available.</li>") + "</ul>")
    parts.append("<h2>Appendix: telemetry summary</h2><pre>" + _e("\n".join(bundle.telemetry_lines)) + "</pre>")
    parts.append("<hr><p class='muted'>PlantMind is advisory only: it never sends commands to equipment. "
                 "Every action above is a suggestion for a human to decide.</p></body></html>")
    return "".join(parts)
