"""Smoke test against the real model. Skipped without GROQ_API_KEY."""

import os

import pytest

pytestmark = pytest.mark.llm


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY") or os.getenv("LLM_PROVIDER") == "stub", reason="needs GROQ_API_KEY")
def test_real_agent_checks_balance():
    from hragent.agent import HRAgent
    from hragent.config import get_settings
    from hragent.hr_system import HRSystem
    from hragent.llm import GroqClient

    settings = get_settings()
    response = HRAgent(HRSystem(), settings=settings, llm=GroqClient(settings)).send("How many casual leaves do I have?")
    assert any(s.tool == "get_leave_balance" for s in response.tool_steps)
    assert "6" in response.answer
