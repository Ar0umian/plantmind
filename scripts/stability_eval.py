#!/usr/bin/env python3
"""Repeats every scenario several times with the REAL models and reports how consistent the top cause is.

Run from the project root:
    python scripts/stability_eval.py --runs 3        # real services; about 2 model calls per run; spends credits
    python scripts/stability_eval.py --dry-run       # offline mock, only checks this script
Writes out/stability.md (no keys). Use its numbers in the README instead of a single lucky run.
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

SCENARIOS = [("logic_tamper", 120, "logic_tampering"), ("spoofed_reading", 140, "spoofing"),
             ("sensor_fault", 60, "sensor_fault"), ("abnormal_command", 20, "command_abuse")]

parser = argparse.ArgumentParser()
parser.add_argument("--runs", type=int, default=3)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

os.environ["MOCK_LLM"] = "1" if args.dry_run else "0"
os.environ["MOCK_TAVILY"] = "1"

from core.config import get_settings          # noqa: E402  (after the environment is set)

settings = get_settings()
if not args.dry_run:
    missing = [n for n, v in (("NEBIUS_API_KEY", settings.nebius_api_key), ("NEBIUS_BASE_URL", settings.nebius_base_url),
                              ("MODEL_NANO", settings.model_nano), ("MODEL_SUPER", settings.model_super),
                              ("MODEL_ULTRA", settings.model_ultra)) if not v]
    if missing:
        sys.exit("These .env values are empty: " + ", ".join(missing))

from agent.engine import Engine               # noqa: E402

engine = Engine(interval_s=0.0)
usage = engine.llm.usage
rows, total_ok, total_runs = [], 0, 0
started = time.time()
for name, ticks, expected in SCENARIOS:
    labels, seconds, tokens_out, severities = [], [], [], Counter()
    for run in range(args.runs):
        before, t0 = len(usage), time.time()
        engine.start_scenario(name)                 # clears the analysis cache: every run is a fresh model call
        for _ in range(ticks):
            engine.step()
        alerts = engine.alerts()
        top = alerts[0].hypotheses[0].label if alerts and alerts[0].hypotheses else "-"
        labels.append(top)
        if alerts:
            severities[alerts[0].severity.value] += 1
        seconds.append(time.time() - t0)
        tokens_out.append(sum(e.get("completion_tokens") or 0 for e in usage[before:]))
        print(f"[progress] {name} run {run + 1}/{args.runs}: {top} ({seconds[-1]:.0f}s)", flush=True)
    ok = sum(1 for label in labels if label == expected)
    total_ok += ok
    total_runs += len(labels)
    rows.append(f"| {name} | {expected} | {', '.join(labels)} | {ok}/{len(labels)} | "
                f"{dict(severities)} | {sum(seconds) / len(seconds):.0f} | {sum(tokens_out) // len(tokens_out)} |")

mode = "DRY RUN (mock)" if args.dry_run else "LIVE"
lines = ["# PlantMind stability evaluation", "", f"- Mode: {mode}; runs per scenario: {args.runs}; "
         f"date: {time.strftime('%Y-%m-%d %H:%M')}",
         f"- Models: nano=`{settings.model_nano or '-'}`, super=`{settings.model_super or '-'}`, "
         f"ultra=`{settings.model_ultra or '-'}`; no-think tiers: {list(settings.no_think_tiers)}", "",
         "| Scenario | Expected top cause | Top cause per run | Correct | Alert severity | Avg s/run | Avg output tokens/run |",
         "|---|---|---|---|---|---|---|", *rows, "",
         f"**Top-cause accuracy: {total_ok}/{total_runs} runs** (wall time {time.time() - started:.0f}s)",
         f"- Pipeline stats: {engine.analyzer.stats}"]
(ROOT / "out").mkdir(exist_ok=True)
(ROOT / "out" / "stability.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
print("\nSaved: out/stability.md")
