"""LLM clients.

`GroqClient` calls Groq's free OpenAI-compatible API with tool calling.
`ScriptedClient` replays a fixed list of model turns, so unit tests can exercise the
agent loop, tracing and scoring offline without an API key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

from hragent.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it


@dataclass
class ModelTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    model: str

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn: ...


class QuotaExhaustedError(RuntimeError):
    """The provider's daily quota is used up — retrying now will not help."""


class MalformedToolCallError(RuntimeError):
    """The model kept producing tool calls the provider could not parse."""


def _is_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(m in text for m in ("per day", "tokens per day", "requests per day", "(tpd)", "(rpd)"))


class GroqClient:
    def __init__(self, settings: Settings, model: str | None = None, max_retries: int = 6, temperature: float = 0.0):
        if not settings.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add your free key from https://console.groq.com"
            )
        from openai import OpenAI

        self.model = model or settings.agent_model
        self.max_retries = max_retries
        self.temperature = temperature
        self._client = OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)

    def _create(self, **kwargs):
        from openai import APIConnectionError, BadRequestError, InternalServerError, RateLimitError

        malformed = 0
        for attempt in range(self.max_retries):
            try:
                return self._client.chat.completions.create(model=self.model, **kwargs)
            except RateLimitError as exc:
                if _is_daily_limit(exc):
                    raise QuotaExhaustedError(
                        f"Groq daily limit reached for {self.model}. It resets within 24 hours; meanwhile use --limit."
                    ) from exc
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
            except BadRequestError as exc:
                # Groq rejects a turn when the model emits an unparseable tool call.
                if "tool_use_failed" not in str(exc) and "tool call" not in str(exc).lower():
                    raise
                malformed += 1
                if malformed >= 3:
                    raise MalformedToolCallError(str(exc)[:300]) from exc
            except (APIConnectionError, InternalServerError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError("Groq request failed after retries")

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn:
        kwargs: dict = {"messages": messages, "temperature": self.temperature}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        response = self._create(**kwargs)
        msg = response.choices[0].message
        usage = getattr(response, "usage", None)
        return ModelTurn(
            content=msg.content or "",
            tool_calls=[
                ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
                for tc in (msg.tool_calls or [])
            ],
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        """Plain text completion — used by the LLM judge."""
        kwargs: dict = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return self._create(**kwargs).choices[0].message.content or ""


class ScriptedClient:
    """Replays scripted turns. Each item is either a final answer string or a list of
    (tool_name, arguments_dict) tuples to call."""

    model = "scripted"

    def __init__(self, script: list):
        self._script = list(script)
        self.seen_messages: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn:
        self.seen_messages.append([dict(m) for m in messages])
        if not self._script:
            return ModelTurn(content="")
        step = self._script.pop(0)
        if isinstance(step, str):
            return ModelTurn(content=step)
        calls = [
            ToolCall(id=f"call_{len(self.seen_messages)}_{i}", name=name, arguments=json.dumps(args))
            for i, (name, args) in enumerate(step)
        ]
        return ModelTurn(tool_calls=calls)


def get_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "groq":
        return GroqClient(settings)
    raise ValueError(f"LLM_PROVIDER={settings.llm_provider!r} needs an injected client (tests use ScriptedClient).")
