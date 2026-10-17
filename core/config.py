"""Environment-based settings. Read fresh on every call so tests can override."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    nebius_api_key: str
    nebius_base_url: str
    model_nano: str
    model_super: str
    model_ultra: str
    tavily_api_key: str
    mock_llm: bool
    mock_tavily: bool
    telemetry_interval_s: float
    host: str
    port: int


def get_settings() -> Settings:
    return Settings(
        nebius_api_key=os.getenv("NEBIUS_API_KEY", ""),
        nebius_base_url=os.getenv("NEBIUS_BASE_URL", ""),
        model_nano=os.getenv("MODEL_NANO", ""),
        model_super=os.getenv("MODEL_SUPER", ""),
        model_ultra=os.getenv("MODEL_ULTRA", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        mock_llm=_flag("MOCK_LLM", True),
        mock_tavily=_flag("MOCK_TAVILY", True),
        telemetry_interval_s=float(os.getenv("TELEMETRY_INTERVAL_S", "1")),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
