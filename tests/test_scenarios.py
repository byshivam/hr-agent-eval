"""Validate the scenario set itself, using scripted reference and broken agents."""

import pytest

from hragent.config import get_settings
from hragent.llm import ScriptedClient

from evals.dataset import load_scenarios
from evals.judge import build_metrics
from evals.run_eval import aggregate, decide, evaluate
from tests.reference_scripts import BROKEN, REFERENCE

SCENARIOS = {s.id: s for s in load_scenarios()}


def run(script_by_id, ids, metrics=None):
    scenarios = [SCENARIOS[i] for i in ids]
    records, incomplete = evaluate(
        scenarios, get_settings(), lambda s: ScriptedClient(script_by_id[s.id]), "v2", metrics, log=lambda _m: None
    )
    assert not incomplete
    return {r["id"]: r for r in records}


def test_every_scenario_has_a_reference_script():
    assert set(REFERENCE) == set(SCENARIOS)
    assert len(SCENARIOS) >= 20


@pytest.mark.parametrize("scenario_id", sorted(REFERENCE))
def test_reference_agent_passes(scenario_id):
    record = run(REFERENCE, [scenario_id])[scenario_id]
    assert record["failures"] == [], record["scores"]["notes"]


@pytest.mark.parametrize("scenario_id", sorted(BROKEN))
def test_broken_agent_is_caught(scenario_id):
    script, expected_failures = BROKEN[scenario_id]
    record = run({scenario_id: script}, [scenario_id])[scenario_id]
    assert expected_failures <= set(record["failures"]), (record["failures"], record["scores"]["notes"])


def test_reference_run_is_go_and_deepeval_tool_correctness_agrees():
    metrics = build_metrics(get_settings(), use_llm_judge=False)
    records = list(run(REFERENCE, list(SCENARIOS), metrics).values())
    summary = aggregate(records)
    assert summary["pass_rate"] == 1.0
    assert summary["unsafe_action_rate"] == 0.0
    assert summary["tool_correctness"] == 1.0
    import json
    from evals.run_eval import THRESHOLDS_PATH
    decision, reasons = decide(summary, None, json.loads(THRESHOLDS_PATH.read_text()))
    assert decision == "GO", reasons
