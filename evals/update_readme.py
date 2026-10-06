"""Refresh the "Latest results" block in README.md from the newest report.

Usage:
    python -m evals.update_readme reports/latest.json [--previous previous.json]

Only the text between the RESULTS markers is replaced. Incomplete runs (for example
when the free-tier quota runs out) are skipped, so the README never shows a
half-finished result.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from hragent.config import PROJECT_ROOT

START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"

LABELS = {
    "pass_rate": "Scenarios fully passed",
    "tool_selection_accuracy": "Right tool chosen",
    "argument_accuracy": "Correct tool arguments (dates, ids)",
    "task_completion_rate": "Task completed (HR system end state)",
    "answer_accuracy": "Final answer correct",
    "clarification_rate": "Asks before acting on vague requests",
    "error_honesty": "Honest about tool errors & pending status",
    "policy_adherence": "Follows leave policy",
    "privacy_pass_rate": "Privacy (no access to colleagues' data)",
    "unsafe_action_rate": "Unrequested / unsafe actions",
    "tool_correctness": "Tool correctness (DeepEval)",
    "response_quality": "Response quality (LLM judge)",
}


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _delta(name: str, value: float, previous: dict | None, lower_is_better: bool) -> str:
    if not previous or previous.get(name) is None:
        return "—"
    diff = value - previous[name]
    if abs(diff) < 0.005:
        return "no change"
    better = diff < 0 if lower_is_better else diff > 0
    return f"{'🟢' if better else '🔴'} {diff * 100:+.0f} pts"


def render(report: dict, previous: dict | None = None) -> str:
    summary, gates = report["summary"], report["thresholds"]
    prev = previous["summary"] if previous else None
    icon = "✅" if report["decision"] == "GO" else "⛔"
    judge = f" · judge `{report['judge_model']}`" if report.get("judge_model") else ""
    lines = [
        START,
        f"**Last run:** {report['run_at']} · `{report['agent_model']}` · prompt `{report['prompt_version']}`{judge} "
        f"· {report['n_scenarios']} scenarios · **{icon} {report['decision']}**",
        "",
        "| Check | Score | Gate | Status | vs previous run |",
        "|---|---|---|---|---|",
    ]
    for name, label in LABELS.items():
        value = summary.get(name)
        if value is None:
            continue
        lower = name in gates["max"]
        gate = gates["max"].get(name) if lower else gates["min"].get(name)
        ok = gate is None or (value <= gate if lower else value >= gate)
        gate_txt = f"{'≤' if lower else '≥'} {_pct(gate)}" if gate is not None else "—"
        lines.append(f"| {label} | **{_pct(value)}** | {gate_txt} | {'✅' if ok else '❌'} | {_delta(name, value, prev, lower)} |")
    if summary.get("avg_tool_calls") is not None:
        lines.append(f"| Avg tool calls per scenario | {summary['avg_tool_calls']} | — | — | — |")
    if summary.get("p50_latency_s") is not None:
        lines.append(f"| Median latency | {summary['p50_latency_s']:.1f} s | — | — | — |")

    cats = report.get("by_category") or {}
    if cats:
        lines += ["", "**By category:** " + " · ".join(f"{c} {v['passed']}/{v['total']}" for c, v in cats.items())]
    failing = [c for c in report["cases"] if c["failures"]]
    lines += ["", f"**Findings this run ({len(failing)} failing of {report['n_scenarios']}):**", ""]
    if not failing:
        lines.append("- No failing scenarios 🎉")
    for case in failing[:8]:
        detail = "; ".join(case["scores"]["notes"][:2]) or ", ".join(case["failures"])
        lines.append(f"- `{case['id']}` ({case['category']}): {detail}")
    if len(failing) > 8:
        lines.append(f"- …and {len(failing) - 8} more in the full report")
    if report["reasons"]:
        lines += ["", "**Gate notes:** " + "; ".join(report["reasons"])]
    lines.append(END)
    return "\n".join(lines)


def is_complete(report: dict) -> bool:
    return not any(r.startswith("evaluation incomplete") for r in report.get("reasons", []))


def update(readme: Path, report: dict, previous: dict | None = None) -> bool:
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise ValueError(f"{readme.name} has no {START} … {END} block")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    new_text = pattern.sub(lambda _: render(report, previous), text, count=1)
    if new_text == text:
        return False
    readme.write_text(new_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--readme", type=Path, default=PROJECT_ROOT / "README.md")
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not is_complete(report):
        print("Run was incomplete — README left unchanged.")
        return 0
    previous = None
    if args.previous and args.previous.exists() and args.previous.stat().st_size:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
    changed = update(args.readme, report, previous)
    print("README updated." if changed else "README already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
