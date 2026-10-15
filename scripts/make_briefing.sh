#!/bin/bash
# Creates out/briefing.txt to resume the project in a new chat.
set -e
cd "$(dirname "$0")/.."
mkdir -p out
OUT="out/briefing.txt"
{
  echo "You are Claude, working with Aram on the PlantMind hackathon project (Nebius x NVIDIA Global AI Hackathon)."
  echo "Read every file below. Follow docs/BUILD_PLAN.md. Deliver code as copy-paste Terminal commands (cat heredocs), split across several messages, working directory ~/plantmind."
  echo "First reply: confirm which step is next, based on docs/CHANGELOG.md and the file list, then wait for Aram."
  echo
  echo "=================== FILE TREE ==================="
  find . -path ./venv -prune -o -path ./.git -prune -o -path ./out -prune -o -name __pycache__ -prune -o -type f -print | sort
  echo
  for f in docs/*.md core/*.py; do
    echo "=================== FILE: $f ==================="
    cat "$f"
    echo
  done
} > "$OUT"
echo "Created $OUT ($(wc -c < "$OUT") bytes)"
