#!/usr/bin/env python3
"""Live evaluation: runs the REAL services (Nemotron on Nebius Token Factory, Tavily) end to end,
measures them, and writes a Markdown report you can paste into the README and the feedback notes.

Run from the project root:
    python scripts/live_eval.py              # real services; needs keys in .env; SPENDS CREDITS
    python scripts/live_eval.py --dry-run    # offline mock; only checks that this script works

The report (out/live_eval.md) contains no keys.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DRY = "--dry-run" in sys.argv
os.environ["MOCK_LLM"] = "1" if DRY else "0"
os.environ["MOCK_TAVILY"] = "1" if DRY else "0"

from core.config import get_settings          # noqa: E402  (after the environment is set)

SCENARIOS = [("logic_tamper", 120, "logic_tampering"), ("spoofed_reading", 140, "spoofing"),
             ("sensor_fault", 60, "sensor_fault"), ("abnormal_command", 20, "command_abuse")]


def preflight() -> None:
    s = get_settings()
    missing = [name for name, value in (
        ("NEBIUS_API_KEY", s.nebius_api_key), ("NEBIUS_BASE_URL", s.nebius_base_url),
        ("MODEL_NANO", s.model_nano), ("MODEL_SUPER", s.model_super), ("MODEL_ULTRA", s.model_ultra),
        ("TAVILY_API_KEY", s.tavily_api_key)) if not value]
    if missing:
        sys.exit("Cannot run the live evaluation. These .env values are empty: " + ", ".join(missing)
                 + "\nFill them first (see README, 'Live mode'), then run again.")


def totals(entries):
    calls = len(entries)
    prompt = sum(e.get("prompt_tokens") or 0 for e in entries)
    completion = sum(e.get("completion_tokens") or 0 for e in entries)
    seconds = sum(e.get("seconds") or 0 for e in entries)
    return calls, prompt, completion, seconds


def main() -> None:
    if not DRY:
        preflight()
    from agent.engine import Engine
    started = time.time()
    engine = Engine(interval_s=0.0)
    usage = engine.llm.usage
    mode = "DRY RUN (mock, nothing real was called)" if DRY else "LIVE (Nemotron on Nebius Token Factory + Tavily)"
    lines = [f"# PlantMind live evaluation", "", f"- Mode: {mode}",
             f"- Date: {time.strftime('%Y-%m-%d %H:%M')}",
             f"- Models: nano=`{get_settings().model_nano or '-'}`, super=`{get_settings().model_super or '-'}`, "
             f"ultra=`{get_settings().model_ultra or '-'}`", "",
             "## Incident analysis per scenario", "",
             "| Scenario | Expected top cause | Got | Match | Tier | LLM calls | Tokens (in/out) | LLM seconds | Notes |",
             "|---|---|---|---|---|---|---|---|---|"]
    correct = 0
    for name, ticks, expected in SCENARIOS:
        before = len(usage)
        engine.start_scenario(name)
        for _ in range(ticks):
            engine.step()
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else "-"
        tier = alerts[0].triage_tier if alerts else "-"
        entries = usage[before:]
        calls, tin, tout, secs = totals(entries)
        notes = []
        for result in list(engine.analyzer._cache.values())[-1:]:
            notes = result.notes
        ok = top == expected
        correct += ok
        lines.append(f"| {name} | {expected} | {top} | {'yes' if ok else 'NO'} | {tier} | {calls} | "
                     f"{tin}/{tout} | {secs:.1f} | {'; '.join(notes)[:80] or '-'} |")

    engine.start_scenario("logic_tamper")
    engine.step()
    guard = engine.guard_running()
    for _ in range(120):                      # let the incident develop before the assistant and report checks
        engine.step()
    lines += ["", "## Change Guard (tampered program vs approved)", ""]
    if guard is None:
        lines.append("- No result.")
    else:
        lines.append(f"- Assessment mode: `{guard.mode}` (live = real model text; unavailable = rule-based text only)")
        lines.append(f"- Overall severity: {guard.report.overall_severity.value}; findings: {len(guard.report.findings)}")
        for f in guard.report.findings:
            lines.append(f"  - {f.id} rule={f.rule_severity.value} final={f.final_severity().value}: {f.summary[:90]}")

    lines += ["", "## Assistant", ""]
    for question in ("What is happening?", "What does IL-04 do?", "Why does P-201 stop?", "stop P-201"):
        t0 = time.time()
        reply = engine.ask(question)
        lines.append(f"- `{question}` -> mode `{reply.mode}`, {time.time() - t0:.1f}s, sources {reply.sources}: "
                     f"{reply.answer[:100]!r}")

    doc = engine.plant_document()
    lines += ["", "## Plant document", "", f"- Overview mode: `{doc.summary_mode}` (deterministic means the model text was "
              f"rejected or unavailable)"]

    lines += ["", "## Incident report and Tavily", ""]
    alerts = engine.alerts()
    if alerts:
        bundle = engine.incident_report_bundle(alerts[0].id)
        lines.append(f"- References attached: {len(bundle.report.references)}")
        for ref in bundle.report.references:
            lines.append(f"  - {ref.title[:80]} - {ref.url}")
        lines.append(f"- Tavily stats: {engine.tavily.stats}")
    else:
        lines.append("- No alert was available for a report.")

    calls, tin, tout, secs = totals(usage)
    by_tier = {}
    for entry in usage:
        by_tier.setdefault(entry.get("tier", "?"), []).append(entry)
    lines += ["", "## Totals", "",
              f"- Model calls: {calls}; tokens in/out: {tin}/{tout}; total model seconds: {secs:.1f}",
              f"- Pipeline stats: {engine.analyzer.stats}",
              f"- Top-cause accuracy: {correct}/{len(SCENARIOS)} scenarios",
              f"- Wall time: {time.time() - started:.0f}s", "", "| Tier | Calls | Avg seconds | Tokens in/out |", "|---|---|---|---|"]
    for tier, entries in sorted(by_tier.items()):
        c, i, o, s = totals(entries)
        lines.append(f"| {tier} | {c} | {s / c:.1f} | {i}/{o} |")
    lines += ["", "## What to do with this", "",
              "- Paste the Totals and the tier table into README.md where it says TODO(live).",
              "- Any `NO` in the match column, `unavailable`, or validator notes means a prompt needs tuning: send me this file.",
              "- Copy interesting observations into docs/FEEDBACK_NOTES.md."]

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "live_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved: out/live_eval.md")


if __name__ == "__main__":
    main()
