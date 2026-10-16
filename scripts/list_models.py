"""Lists the model IDs your Nebius Token Factory key can use (filters for Nemotron).

Run from the project root:  python scripts/list_models.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI

key = os.getenv("NEBIUS_API_KEY", "")
base = os.getenv("NEBIUS_BASE_URL") or "https://api.tokenfactory.nebius.com/v1/"
if not key:
    print("NEBIUS_API_KEY is empty in .env - fill it first (open -e .env)")
    sys.exit(1)

try:
    client = OpenAI(api_key=key, base_url=base)
    ids = sorted(model.id for model in client.models.list())
except Exception as exc:
    print("Could not list models:", exc)
    sys.exit(1)

print(f"{len(ids)} models available on {base}")
hits = [i for i in ids if "nemotron" in i.lower()]
print("\nNemotron models:" if hits else "\nNo model with 'nemotron' in its ID was found.")
for model_id in hits:
    print("  ", model_id)
if not hits:
    print("\nAll IDs (look for NVIDIA ones):")
    for model_id in ids:
        print("  ", model_id)
