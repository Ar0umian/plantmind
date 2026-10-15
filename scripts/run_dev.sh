#!/bin/bash
# Starts PlantMind at http://127.0.0.1:8000
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
