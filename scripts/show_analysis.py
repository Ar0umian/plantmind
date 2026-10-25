#!/usr/bin/env python3
"""Shows what the model concluded for ONE scenario, several times, to see why and how consistent it is.

Run from the project root:
    python scripts/show_analysis.py --scenario abnormal_command --runs 3
Options:
    --show-prompt   also print the exact text the deep-analysis model received (last run)
    --dry-run       offline mock (checks the script only)
Real runs spend credits (about 2 model calls per run). The output contains no keys.
"""
import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

TICKS = {"logic_tamper": 120, "spoofed_reading": 140, "sensor_fault": 60, "abnormal_command": 20, "normal": 60}

parser = argparse.ArgumentParser()
parser.add_argument("--scenario", default="abnormal_command", choices=sorted(TICKS))
parser.add_argument("--runs", type=int, default=3)
parser.add_argument("--show-prompt", action="store_true")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

os.environ["MOCK_LLM"] = "1" if args.dry_run else "0"
os.environ["MOCK_TAVILY"] = "1"                      # Tavily is not needed here

from agent.engine import Engine                      # noqa: E402  (after the environment is set)


def short(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


engine = Engine(interval_s=0.0)
captured = []
original = engine.llm.generate_json


def spy(tier, system, user, schema, **kwargs):
    captured.append((tier, schema.__name__, user))
    return original(tier, system, user, schema, **kwargs)


engine.llm.generate_json = spy
labels = Counter()
for run in range(1, args.runs + 1):
    before = len(engine.llm.usage)
    started = time.time()
    engine.start_scenario(args.scenario)             # also clears the analysis cache: a fresh model call
    for _ in range(TICKS[args.scenario]):
        engine.step()
    alerts = engine.alerts()
    print(f"\n===== run {run}/{args.runs}  scenario={args.scenario}  ({time.time() - started:.0f}s) =====")
    if not alerts:
        print("No alert was raised.")
        continue
    alert = alerts[0]
    print(f"Alert {alert.id} [{alert.severity.value}] {alert.title}   tier={alert.triage_tier}")
    for ev in alert.evidence:
        print(f"  evidence {ev.id} [{ev.kind}] {short(ev.summary, 150)}")
    for h in alert.hypotheses:
        print(f"  -> {h.label:16} {round(h.confidence * 100):3d}%  cites {h.evidence_ids}")
        print(f"       why: {short(h.reasoning, 260)}")
    print(f"  explanation: {short(alert.operator_explanation, 400)}")
    print(f"  suggested checks: {len(alert.recommended_actions)}")
    for result in list(engine.analyzer._cache.values())[-1:]:
        if result.notes:
            print(f"  validator notes: {result.notes}")
    entries = engine.llm.usage[before:]
    print(f"  model calls: {len(entries)}, tokens in/out: "
          f"{sum(e.get('prompt_tokens') or 0 for e in entries)}/{sum(e.get('completion_tokens') or 0 for e in entries)}")
    if alert.hypotheses:
        labels[alert.hypotheses[0].label] += 1

print(f"\nTop cause over {args.runs} run(s): {dict(labels)}")
if args.show_prompt:
    deep = [c for c in captured if c[1] == "ReasonerOutput"]
    if deep:
        print("\n===== text sent to the deep-analysis model (last run) =====\n" + deep[-1][2])
