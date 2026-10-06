import json

from hragent.agent import STEP_LIMIT_MESSAGE, HRAgent
from hragent.config import get_settings
from hragent.hr_system import HRSystem
from hragent.llm import ModelTurn, ScriptedClient, ToolCall


def test_tool_loop_records_trace_and_feeds_results_back():
    llm = ScriptedClient([[("get_leave_balance", {})], "You have 6 casual leaves."])
    agent = HRAgent(HRSystem(), settings=get_settings(), llm=llm)
    response = agent.send("casual balance?")
    assert response.answer == "You have 6 casual leaves."
    [step] = response.tool_steps
    assert step.tool == "get_leave_balance" and step.ok
    tool_msg = llm.seen_messages[1][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["available_days"]["casual"] == 6


def test_system_prompt_has_frozen_date_and_user():
    agent = HRAgent(HRSystem(current_user="E1002"), settings=get_settings(), llm=ScriptedClient(["hi"]))
    system = agent.messages[0]["content"]
    assert "Wednesday, 2026-10-07" in system and "Rahul Verma" in system


def test_multi_turn_keeps_history():
    llm = ScriptedClient(["Which type?", "ok"])
    agent = HRAgent(HRSystem(), settings=get_settings(), llm=llm)
    agent.send("leave on 12 Oct")
    agent.send("casual")
    roles = [m["role"] for m in llm.seen_messages[-1]]
    assert roles == ["system", "user", "assistant", "user"]


def test_bad_arguments_return_an_error_to_the_model():
    class BadArgs:
        model = "bad"
        calls = 0

        def complete(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ModelTurn(tool_calls=[ToolCall("c1", "apply_leave", "{not json")])
            return ModelTurn(content="Sorry, something went wrong.")

    response = HRAgent(HRSystem(), settings=get_settings(), llm=BadArgs()).send("apply")
    assert response.tool_steps[0].result["error"]["code"] == "INVALID_ARGUMENTS"


def test_step_limit_stops_runaway_loops():
    llm = ScriptedClient([[("get_leave_balance", {})]] * 50)
    response = HRAgent(HRSystem(), settings=get_settings(), llm=llm).send("loop")
    assert response.hit_step_limit and response.answer == STEP_LIMIT_MESSAGE
