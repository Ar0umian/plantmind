#!/bin/bash
# usage: scripts/make_briefing.sh A|B
set -e
W="$1"
if [ "$W" != "A" ] && [ "$W" != "B" ]; then
  echo "usage: scripts/make_briefing.sh A|B"
  exit 1
fi
cd "$(dirname "$0")/.."
mkdir -p out
OUT="out/briefing_${W}.txt"
if [ "$W" = "A" ]; then
  ROLE="Workstream A (Plant and Knowledge): you own plant/, knowledge/, api/routers/knowledge.py, api/routers/guard.py and their tests."
else
  ROLE="Workstream B (Agent and Experience): you own agent/, web/, api/main.py, api/routers/telemetry.py, alerts.py, assistant.py, reports.py, scenarios.py and their tests."
fi
{
  echo "You are Claude, working with Aram on the PlantMind hackathon project (Nebius x NVIDIA Global AI Hackathon)."
  echo "$ROLE"
  echo "Rules: read every file below first. Write only inside your own folders. Do not change core/, fixtures/, data/ or docs/ without asking Aram."
  echo "Deliver code as copy-paste Terminal commands (cat heredocs), split across several messages, working directory ~/plantmind."
  echo "First reply: summarize your tasks from docs/WORK_SPLIT.md and list any contract questions. Then wait for Aram."
  echo
  for f in docs/*.md core/*.py; do
    echo "=================== FILE: $f ==================="
    cat "$f"
    echo
  done
} > "$OUT"
echo "Created $OUT ($(wc -c < "$OUT") bytes)"
