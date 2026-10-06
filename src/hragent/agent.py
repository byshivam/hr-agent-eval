"""The HR agent: a tool-calling loop that records a full trace of every step.

The trace — each model turn, each tool call with its arguments, result and latency —
is what the evaluation scores. Judging only the final message would miss an agent that
says "done" without doing anything, or one that leaks data in a tool call it never
mentions.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from hragent.config import Settings, get_settings
from hragent.hr_system import HRSystem
from hragent.llm import LLMClient, MalformedToolCallError, get_llm
from hragent.prompts import build_system_prompt
from hragent.tools import TOOL_SCHEMAS, ToolExecutor

STEP_LIMIT_MESSAGE = "Sorry, I couldn't finish that request. Please try again or raise an HR ticket."


@dataclass
class TraceStep:
    kind: str  # "model" | "tool" | "error"
    latency_s: float = 0.0
    content: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    ok: bool = True
    tokens: int = 0


@dataclass
class AgentResponse:
    answer: str
    steps: list[TraceStep]
    hit_step_limit: bool = False
    latency_s: float = 0.0

    @property
    def tool_steps(self) -> list[TraceStep]:
        return [s for s in self.steps if s.kind == "tool"]


class HRAgent:
    def __init__(
        self,
        hr: HRSystem,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        prompt_version: str | None = None,
    ):
        self.settings = settings or get_settings()
        self.hr = hr
        self.llm = llm or get_llm(self.settings)
        self.executor = ToolExecutor(hr, self.settings)
        version = prompt_version or self.settings.prompt_version
        profile = _profile(hr)
        self.messages: list[dict] = [{"role": "system", "content": build_system_prompt(version, profile, hr.today)}]

    def send(self, user_message: str) -> AgentResponse:
        """Handle one user turn. Conversation history is kept for multi-turn scenarios."""
        self.messages.append({"role": "user", "content": user_message})
        steps: list[TraceStep] = []
        started = time.perf_counter()

        for _ in range(self.settings.max_steps):
            t0 = time.perf_counter()
            try:
                turn = self.llm.complete(self.messages, TOOL_SCHEMAS)
            except MalformedToolCallError as exc:
                steps.append(TraceStep(kind="error", content=f"malformed tool call: {exc}", ok=False))
                answer = STEP_LIMIT_MESSAGE
                self.messages.append({"role": "assistant", "content": answer})
                return AgentResponse(answer, steps, hit_step_limit=True, latency_s=time.perf_counter() - started)
            steps.append(
                TraceStep(
                    kind="model", latency_s=round(time.perf_counter() - t0, 3), content=turn.content,
                    tokens=turn.prompt_tokens + turn.completion_tokens,
                )
            )
            if not turn.tool_calls:
                self.messages.append({"role": "assistant", "content": turn.content})
                return AgentResponse(turn.content.strip(), steps, latency_s=round(time.perf_counter() - started, 3))

            self.messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or None,
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in turn.tool_calls
                    ],
                }
            )
            for tc in turn.tool_calls:
                t1 = time.perf_counter()
                args, result, ok = self.executor.execute(tc.name, tc.arguments)
                steps.append(
                    TraceStep(
                        kind="tool", tool=tc.name, args=args, result=result, ok=ok,
                        latency_s=round(time.perf_counter() - t1, 4),
                    )
                )
                self.messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)}
                )

        self.messages.append({"role": "assistant", "content": STEP_LIMIT_MESSAGE})
        return AgentResponse(STEP_LIMIT_MESSAGE, steps, hit_step_limit=True, latency_s=round(time.perf_counter() - started, 3))


def _profile(hr: HRSystem) -> dict:
    """Profile for the system prompt, read directly so fault injection can't break setup."""
    from hragent.hr_system import EMPLOYEES

    return EMPLOYEES[hr.current_user]
