"""Single LLM client for PlantMind (Nebius Token Factory, OpenAI-compatible API).

- Tiers: nano (fast triage), super / ultra (deep reasoning), mapped to
  MODEL_NANO / MODEL_SUPER / MODEL_ULTRA from the environment.
- MOCK_LLM=1: no network call. Callers pass a `mock` factory that returns a
  realistic result, so the full flow runs offline and in tests.
- JSON output is validated against a pydantic schema with retries.
"""
import json
import re
import time
from typing import Callable, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
TIERS = ("nano", "super", "ultra")


class LLMError(Exception):
    pass


def _extract_json(raw: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start:end + 1]


class LLMClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.usage: List[dict] = []
        self._client = None

    @property
    def is_mock(self) -> bool:
        return self.settings.mock_llm

    # ------------------------------------------------------------ internals
    def _model_for(self, tier: str) -> str:
        if tier not in TIERS:
            raise ValueError(f"unknown tier '{tier}', expected one of {TIERS}")
        model = {"nano": self.settings.model_nano,
                 "super": self.settings.model_super,
                 "ultra": self.settings.model_ultra}[tier]
        if not model:
            raise LLMError(f"MODEL_{tier.upper()} is not set in .env")
        return model

    def _get_client(self):
        if self._client is None:
            if not self.settings.nebius_api_key or not self.settings.nebius_base_url:
                raise LLMError("NEBIUS_API_KEY / NEBIUS_BASE_URL are not set in .env")
            from openai import OpenAI
            self._client = OpenAI(api_key=self.settings.nebius_api_key,
                                  base_url=self.settings.nebius_base_url)
        return self._client

    def _chat(self, tier: str, system: str, user: str) -> str:
        model = self._model_for(tier)
        client = self._get_client()
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                started = time.time()
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=0.2,
                )
                usage = getattr(resp, "usage", None)
                self.usage.append({
                    "tier": tier, "model": model,
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "seconds": round(time.time() - started, 2),
                })
                return resp.choices[0].message.content or ""
            except Exception as exc:  # network or API error
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM call failed after retries: {last_exc}")

    # --------------------------------------------------------------- public
    def generate_text(self, tier: str, system: str, user: str,
                      mock: Optional[str] = None) -> str:
        if self.is_mock:
            self.usage.append({"tier": tier, "model": "mock"})
            return mock if mock is not None else "[mock response]"
        return self._chat(tier, system, user)

    def generate_json(self, tier: str, system: str, user: str,
                      schema: Type[T],
                      mock: Optional[Callable[[], Union[T, dict]]] = None,
                      max_retries: int = 2) -> T:
        if self.is_mock:
            if mock is None:
                raise LLMError(
                    f"MOCK_LLM is on and no mock factory was given for {schema.__name__}")
            self.usage.append({"tier": tier, "model": "mock"})
            result = mock()
            data = result.model_dump() if isinstance(result, BaseModel) else result
            return schema.model_validate(data)

        schema_text = json.dumps(schema.model_json_schema())
        full_system = (system + "\n\nRespond with ONLY one JSON object that matches this "
                       "JSON Schema. No markdown, no commentary.\n" + schema_text)
        prompt = user
        last_err: Optional[Exception] = None
        for _ in range(max_retries + 1):
            raw = self._chat(tier, full_system, prompt)
            try:
                return schema.model_validate_json(_extract_json(raw))
            except (ValidationError, ValueError) as exc:
                last_err = exc
                prompt = (user + "\n\nYour previous answer was invalid: "
                          + str(exc)[:500] + "\nReturn corrected JSON only.")
        raise LLMError(f"Invalid JSON from model after retries: {last_err}")
