import json

from evals.update_readme import END, START, is_complete, update


def _report(decision="GO", reasons=()):
    return {
        "run_at": "2026-10-07 02:00 UTC", "agent_model": "m", "judge_model": None, "prompt_version": "v2",
        "n_scenarios": 1, "decision": decision, "reasons": list(reasons),
        "summary": {"pass_rate": 1.0, "unsafe_action_rate": 0.0, "avg_tool_calls": 1.0, "p50_latency_s": 1.2},
        "thresholds": {"min": {"pass_rate": 0.8}, "max": {"unsafe_action_rate": 0.0}},
        "by_category": {"privacy": {"passed": 1, "total": 1}},
        "cases": [{"id": "PV-01", "category": "privacy", "failures": [], "scores": {"notes": []}}],
    }


def test_only_the_results_block_changes(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{START}\nold\n{END}\noutro\n")
    assert update(readme, _report())
    text = readme.read_text()
    assert text.startswith("intro") and text.endswith("outro\n") and "100%" in text and "old" not in text


def test_incomplete_runs_are_skipped():
    assert not is_complete(_report("NO-GO", ["evaluation incomplete — quota"]))
