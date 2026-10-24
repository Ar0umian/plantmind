"""Probe: how can the model's hidden reasoning ("thinking") be reduced on Token Factory?

The first live run showed far more output tokens than the JSON answers need, which makes chat answers slow
(up to 26 s). This script sends the SAME small task to the Nano tier in a few variants and reports tokens,
seconds, whether the JSON is valid and whether a <think> block appears. It spends only a few credits.

Run from the project root:   python scripts/probe_reasoning.py
Dry run (no network):        python scripts/probe_reasoning.py --dry-run
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm_client import _extract_json

SYSTEM = ("You are an assistant for a water treatment plant. Reply with ONLY one JSON object "
          'like {"answer": "...", "sources": ["IL-04"]}. At most 3 sentences.')
USER = ("Context: IL-04 trips the chlorine dosing pump P-201 when AT-201 is above 4.0 ppm (chlorine overdose protection). "
        "Question: What does IL-04 do?")

# (name, text added to the system prompt, extra request fields, max_tokens)
VARIANTS = [
    ("baseline", "", None, None),
    ("system suffix /no_think", "\n/no_think", None, None),
    ("chat template enable_thinking=false", "", {"chat_template_kwargs": {"enable_thinking": False}}, None),
    ("reasoning_effort=low", "", {"reasoning_effort": "low"}, None),
]


def run_variant(client, model, name, suffix, extra_body, max_tokens):
    kwargs = {"model": model, "temperature": 0.2,
              "messages": [{"role": "system", "content": SYSTEM + suffix}, {"role": "user", "content": USER}]}
    if extra_body:
        kwargs["extra_body"] = extra_body
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    started = time.time()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:                      # a variant the server rejects is useful information
        return {"variant": name, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    seconds = round(time.time() - started, 2)
    message = resp.choices[0].message
    content = message.content or ""
    try:
        json.loads(_extract_json(content))
        valid = True
    except Exception:
        valid = False
    usage = getattr(resp, "usage", None)
    return {"variant": name, "seconds": seconds,
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "think_in_content": "<think>" in content,
            "separate_reasoning_field": bool(getattr(message, "reasoning_content", None)
                                             or getattr(message, "reasoning", None)),
            "finish_reason": resp.choices[0].finish_reason, "valid_json": valid}


def main():
    dry = "--dry-run" in sys.argv
    if dry:
        from types import SimpleNamespace as NS

        class _Fake:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        msg = NS(content='{"answer": "ok", "sources": []}', reasoning_content=None)
                        return NS(choices=[NS(message=msg, finish_reason="stop")], usage=NS(completion_tokens=20))
        client, model = _Fake(), "dry-run-model"
    else:
        from dotenv import load_dotenv
        load_dotenv()
        key, base, model = (os.getenv("NEBIUS_API_KEY", ""), os.getenv("NEBIUS_BASE_URL", ""),
                            os.getenv("MODEL_NANO", ""))
        if not (key and base and model):
            sys.exit("Fill NEBIUS_API_KEY, NEBIUS_BASE_URL and MODEL_NANO in .env first.")
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=base)
    print(f"Model: {model}\n")
    print(f"{'variant':40} {'sec':>6} {'tokens':>7}  think  field  json  finish   note")
    for name, suffix, extra, max_tokens in VARIANTS:
        r = run_variant(client, model, name, suffix, extra, max_tokens)
        if "error" in r:
            print(f"{name:40} REJECTED: {r['error']}")
            continue
        print(f"{name:40} {r['seconds']:>6} {str(r['completion_tokens']):>7}  "
              f"{'yes' if r['think_in_content'] else 'no':5}  {'yes' if r['separate_reasoning_field'] else 'no':5}  "
              f"{'ok' if r['valid_json'] else 'BAD':4}  {str(r['finish_reason']):8}")
    print("\nHow to read it: pick the variant with valid JSON and the fewest tokens; 'REJECTED' means the "
          "server does not accept that option. Send me this output.")


if __name__ == "__main__":
    main()
