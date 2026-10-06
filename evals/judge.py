"""DeepEval metrics, with Groq as the judge model.

- `tool_correctness` — DeepEval's ToolCorrectnessMetric: were the expected tools called?
  With no `available_tools` it is computed deterministically, so it runs offline too and
  acts as an independent cross-check of our own tool-selection scorer.
- `response_quality` — a G-Eval rubric scored by an LLM judge: is the final reply
  accurate to the tool results, honest about errors and pending status, and concise?
"""

from __future__ import annotations

import asyncio
import json

from deepeval.models import DeepEvalBaseLLM

from hragent.agent import AgentResponse
from hragent.config import Settings
from hragent.llm import GroqClient

from evals.dataset import Scenario

JUDGE_SYSTEM_PROMPT = (
    "You are a strict, impartial evaluator of an HR AI agent. "
    "Follow the requested output format exactly and return valid JSON when asked."
)

RESPONSE_QUALITY_STEPS = [
    "Read the employee's request (input) and the agent's tool calls with their results (context).",
    "Check every fact in the final reply (actual output) — dates, day counts, ids, amounts, names — against the tool results. Penalise any fact the tools did not return.",
    "If a tool returned an error, the reply must say the action did not happen and must not invent data. A submitted leave request must be described as pending, never approved.",
    "If the request was missing details, asking one clear question is the correct behaviour. If it asked for another employee's private data, a polite refusal is correct.",
    "Reward replies that fully complete the request and are short and specific; penalise vague, padded or incomplete replies.",
]


class GroqJudge(DeepEvalBaseLLM):
    def __init__(self, settings: Settings, model_name: str | None = None):
        self._settings = settings
        self._model_name = model_name or settings.judge_model
        super().__init__(self._model_name)

    def load_model(self) -> GroqClient:
        return GroqClient(self._settings, self._model_name)

    def generate(self, prompt: str, schema=None):
        text = self.model.chat(JUDGE_SYSTEM_PROMPT, prompt, json_mode=schema is not None)
        if schema is None:
            return text
        try:
            return schema.model_validate_json(text)
        except Exception:
            return text  # DeepEval falls back to lenient JSON parsing

    async def a_generate(self, prompt: str, schema=None):
        return await asyncio.to_thread(self.generate, prompt, schema)

    def get_model_name(self) -> str:
        return f"groq/{self._model_name}"


class NoLLM(DeepEvalBaseLLM):
    """Placeholder model for metrics that are computed deterministically."""

    def __init__(self):
        super().__init__("none")

    def load_model(self):
        return None

    def generate(self, prompt: str, schema=None):
        raise RuntimeError("this metric should not need an LLM")

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return "deterministic"


def _params():
    try:
        from deepeval.test_case import SingleTurnParams as P
    except ImportError:  # older DeepEval
        from deepeval.test_case import LLMTestCaseParams as P
    return P


def build_metrics(settings: Settings, use_llm_judge: bool) -> dict:
    from deepeval.metrics import GEval, ToolCorrectnessMetric

    metrics = {"tool_correctness": ToolCorrectnessMetric(model=NoLLM(), async_mode=False, include_reason=True)}
    if use_llm_judge:
        P = _params()
        metrics["response_quality"] = GEval(
            name="HR response quality",
            evaluation_steps=RESPONSE_QUALITY_STEPS,
            evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT, P.CONTEXT],
            model=GroqJudge(settings),
            async_mode=False,
        )
    return metrics


def _expected_tools(scenario: Scenario) -> list[str]:
    exp = scenario.expect
    return list(dict.fromkeys(list(exp.get("tools_required", [])) + [c["tool"] for c in exp.get("calls", [])]))


def judge_scenario(scenario: Scenario, responses: list[AgentResponse], metrics: dict) -> dict:
    from deepeval.test_case import LLMTestCase, ToolCall

    from hragent.llm import QuotaExhaustedError

    steps = [s for r in responses for s in r.tool_steps]
    conversation = "\n".join(
        f"Employee: {turn}\nAgent: {resp.answer}" for turn, resp in zip(scenario.turns[:-1], responses[:-1])
    )
    context = [
        f"{s.tool}({json.dumps(s.args, ensure_ascii=False)}) -> {json.dumps(s.result, ensure_ascii=False)[:600]}"
        for s in steps
    ] or ["(no tools were called)"]
    test_case = LLMTestCase(
        input=(conversation + "\nEmployee: " if conversation else "") + scenario.turns[-1],
        actual_output=responses[-1].answer if responses else "",
        context=context,
        tools_called=[ToolCall(name=s.tool, input_parameters=s.args) for s in steps],
        expected_tools=[ToolCall(name=t) for t in _expected_tools(scenario)],
    )
    results = {}
    for name, metric in metrics.items():
        if name == "tool_correctness" and not test_case.expected_tools:
            continue  # nothing to compare against (e.g. pure refusals)
        try:
            metric.measure(test_case)
            results[name] = {"score": round(float(metric.score), 3), "reason": metric.reason}
        except QuotaExhaustedError:
            raise
        except Exception as exc:  # one flaky judge call should not stop the run
            results[name] = {"score": None, "reason": f"judge error: {exc}"}
    return results
