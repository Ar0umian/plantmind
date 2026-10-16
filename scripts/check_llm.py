"""Checks the Nebius Token Factory connection for each model tier (real calls).

Run from the project root:  python scripts/check_llm.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MOCK_LLM"] = "0"

from core.llm_client import LLMClient, LLMError

client = LLMClient()
for tier in ("nano", "super", "ultra"):
    try:
        out = client.generate_text(tier, "You are a terse assistant.",
                                   "Reply with the single word: ready")
        print(f"{tier}: OK -> {out.strip()[:60]!r}")
    except LLMError as exc:
        print(f"{tier}: FAILED -> {exc}")
print("usage:", client.usage)
