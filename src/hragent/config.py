"""Runtime settings, read from environment variables (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# The HR system runs on a frozen clock so that "tomorrow" or "next Monday" always
# resolve to the same dates — every evaluation run is comparable with the last one.
SIMULATED_TODAY = date(2026, 10, 7)  # a Wednesday


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY", ""))
    groq_base_url: str = field(
        default_factory=lambda: _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    )
    agent_model: str = field(default_factory=lambda: _env("AGENT_MODEL", "openai/gpt-oss-20b"))
    judge_model: str = field(default_factory=lambda: _env("JUDGE_MODEL", "openai/gpt-oss-120b"))
    prompt_version: str = field(default_factory=lambda: _env("PROMPT_VERSION", "v3"))
    # "groq" uses the real API; "stub" means tests inject a scripted fake model.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "groq"))
    max_steps: int = field(default_factory=lambda: int(_env("MAX_AGENT_STEPS", "8")))
    policies_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "policies")


def get_settings() -> Settings:
    return Settings()
