"""Checks the Tavily connection with one real search (spends 1 credit).

Run from the project root:  python scripts/check_tavily.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MOCK_TAVILY"] = "0"

from agent.tavily_client import TavilyClient

client = TavilyClient(mock=False)
try:
    results = client._live_search("PLC logic tampering water utility industrial control system advisory", 3)
except Exception as exc:
    message = str(exc)
    if client._api_key:
        message = message.replace(client._api_key, "***")
    print(f"FAILED: {type(exc).__name__}: {message[:200]}")
    print("Hints: 401 = invalid key; 432 = plan limit reached; empty key = fill TAVILY_API_KEY in .env")
    sys.exit(1)

print(f"OK: {len(results)} results")
for item in results:
    print(" -", " ".join(str(item.get("title", "")).split())[:80], "|", item.get("url", ""))
