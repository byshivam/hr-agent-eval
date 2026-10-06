"""Run every scenario against the HR agent and produce a release-readiness report.

Usage:
    python -m evals.run_eval                          # trace scoring + LLM judge
    python -m evals.run_eval --no-judge               # deterministic scoring only (cheaper)
    python -m evals.run_eval --only privacy           # one category, or ids like AR-01,MS-02
    python -m evals.run_eval --prompt-version v1_naive
    python -m evals.run_eval --update-baseline        # approve this run as the baseline

Exit code is 0 when the release decision is GO and 1 when it is NO-GO, so CI blocks a
prompt or model change that makes the agent worse.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from hragent.agent import HRAgent
from hragent.config import PROJECT_ROOT, Settings, get_settings
from hragent.llm import LLMClient, QuotaExhaustedError

from evals.dataset import CATEGORIES, Scenario, load_scenarios
from evals.scorers import score_trace

REPORTS_DIR = PROJECT_ROOT / "reports"
BASELINE_PATH = REPORTS_DIR / "baseline.json"
THRESHOLDS_PATH = Path(__file__).parent / "thresholds.json"
JUDGE_METRICS = ("tool_correctness", "response_quality")


# ------------------------------------------------------------------- running
def run_scenario(scenario: Scenario, settings: Settings, llm: LLMClient, prompt_version: str) -> dict:
    hr = scenario.build_hr()
    agent = HRAgent(hr, settings=settings, llm=llm, prompt_version=prompt_version)
    started = time.perf_counter()
    responses = [agent.send(turn) for turn in scenario.turns]
    latency = round(time.perf_counter() - started, 3)
    score = score_trace(scenario, responses, hr.snapshot())
    return {
        "id": scenario.id,
        "category": scenario.category,
        "description": scenario.description,
        "turns": scenario.turns,
        "answers": [r.answer for r in responses],
        "trace": [
            {"tool": s.tool, "args": s.args, "ok": s.ok, "result": s.result}
            for r in responses for s in r.tool_steps
        ],
        "tokens": sum(s.tokens for r in responses for s in r.steps),
        "latency_s": latency,
        "scores": dataclasses.asdict(score),
        "failures": score.failures(),
        "_responses": responses,
    }


# ---------------------------------------------------------------- aggregating
def _rate(values: list) -> float | None:
    applicable = [v for v in values if v is not None]
    return round(sum(bool(v) for v in applicable) / len(applicable), 3) if applicable else None


def aggregate(records: list[dict]) -> dict:
    sc = [r["scores"] for r in records]

    def passed(cats: tuple[str, ...]) -> float | None:
        return _rate([not r["failures"] for r in records if r["category"] in cats])

    summary = {
        "pass_rate": _rate([not r["failures"] for r in records]),
        "tool_selection_accuracy": _rate([s["tool_selection"] for s in sc]),
        "argument_accuracy": _rate([s["arguments"] for s in sc]),
        "task_completion_rate": _rate([s["task_completion"] for s in sc]),
        "answer_accuracy": _rate([s["answer"] for s in sc]),
        "clarification_rate": _rate([s["clarification"] for s in sc]),
        "error_honesty": passed(("error_handling", "honesty")),
        "policy_adherence": passed(("policy",)),
        "privacy_pass_rate": _rate([s["privacy_ok"] for s in sc]),
        "unsafe_action_rate": _rate([s["unsafe_action"] for s in sc]),
    }
    for name in JUDGE_METRICS:
        vals = [r["judge"][name]["score"] for r in records if r.get("judge", {}).get(name, {}).get("score") is not None]
        summary[name] = round(statistics.mean(vals), 3) if vals else None
    summary["avg_tool_calls"] = round(statistics.mean(s["n_tool_calls"] for s in sc), 2) if sc else None
    summary["redundant_calls"] = sum(s["redundant_calls"] for s in sc)
    summary["p50_latency_s"] = round(statistics.median(r["latency_s"] for r in records), 2) if records else None
    summary["total_tokens"] = sum(r["tokens"] for r in records)
    return summary


def by_category(records: list[dict]) -> dict:
    out = {}
    for cat in CATEGORIES:
        rows = [r for r in records if r["category"] == cat]
        if rows:
            out[cat] = {"passed": sum(not r["failures"] for r in rows), "total": len(rows)}
    return out


INFO_METRICS = {"avg_tool_calls", "redundant_calls", "p50_latency_s", "total_tokens"}


def decide(summary: dict, baseline: dict | None, thresholds: dict) -> tuple[str, list[str]]:
    reasons = []
    for name, minimum in thresholds["min"].items():
        value = summary.get(name)
        if value is not None and value < minimum:
            reasons.append(f"{name} {value:.2f} is below the {minimum:.2f} gate")
    for name, maximum in thresholds["max"].items():
        value = summary.get(name)
        if value is not None and value > maximum:
            reasons.append(f"{name} {value:.2f} is above the {maximum:.2f} limit")
    if baseline:
        tol = thresholds["regression_tolerance"]
        for name, base in baseline["summary"].items():
            value = summary.get(name)
            if name in INFO_METRICS or value is None or base is None:
                continue
            lower_is_better = name in thresholds["max"]
            drop = (value - base) if lower_is_better else (base - value)
            if drop > tol:
                reasons.append(f"{name} regressed from {base:.2f} to {value:.2f} versus baseline")
    return ("GO" if not reasons else "NO-GO"), reasons


# --------------------------------------------------------------------- report
def _fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def write_markdown(report: dict, path: Path) -> None:
    s, base = report["summary"], (report.get("baseline_summary") or {})
    th = report["thresholds"]
    icon = "✅" if report["decision"] == "GO" else "⛔"
    lines = [
        "# Tayal Capital HR Agent — Evaluation Report", "",
        f"**Release decision: {icon} {report['decision']}**", "",
        f"- Run: {report['run_at']}",
        f"- Agent model: `{report['agent_model']}` · prompt `{report['prompt_version']}`",
        f"- Judge: `{report['judge_model'] or 'disabled'}`",
        f"- Scenarios: {report['n_scenarios']}", "",
    ]
    if report["reasons"]:
        lines += ["## Why it is blocked", ""] + [f"- {r}" for r in report["reasons"]] + [""]
    lines += ["## Metrics", "", "| Metric | Value | Gate | Baseline |", "|---|---|---|---|"]
    for name, value in s.items():
        if name in th["max"]:
            gate = f"≤ {th['max'][name]:.2f}"
        elif name in th["min"]:
            gate = f"≥ {th['min'][name]:.2f}"
        else:
            gate = "—"
        lines.append(f"| {name} | {_fmt(value)} | {gate} | {_fmt(base.get(name))} |")
    lines += ["", "## By category", "", "| Category | Passed |", "|---|---|"]
    lines += [f"| {c} | {v['passed']}/{v['total']} |" for c, v in report["by_category"].items()]
    failed = [r for r in report["cases"] if r["failures"]]
    lines += ["", f"## Failing scenarios ({len(failed)})", ""]
    if not failed:
        lines.append("None 🎉")
    for r in failed:
        lines += [f"### {r['id']} · {r['category']}", ""]
        for turn, answer in zip(r["turns"], r["answers"]):
            lines += [f"**Employee:** {turn}", "", f"**Agent:** {answer}", ""]
        if r["trace"]:
            lines.append("**Trace:**")
            lines += [
                f"- `{t['tool']}({json.dumps(t['args'], ensure_ascii=False)})` → {'ok' if t['ok'] else 'error: ' + str(t['result'].get('error', {}).get('code'))}"
                for t in r["trace"]
            ]
            lines.append("")
        lines.append(f"**Failed:** {', '.join(r['failures'])}")
        lines += [f"- {n}" for n in r["scores"]["notes"]]
        for name, res in (r.get("judge") or {}).items():
            if res["score"] is not None and res["score"] < th["min"].get(name, 0):
                lines.append(f"- {name} {res['score']:.2f}: {res['reason']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------- main
def select(scenarios: list[Scenario], only: str | None, limit: int | None) -> list[Scenario]:
    if only:
        keys = {k.strip() for k in only.split(",") if k.strip()}
        scenarios = [s for s in scenarios if s.id in keys or s.category in keys]
    return scenarios[:limit] if limit else scenarios


def evaluate(
    scenarios: list[Scenario],
    settings: Settings,
    llm_factory: Callable[[Scenario], LLMClient],
    prompt_version: str,
    metrics: dict | None = None,
    log: Callable[[str], None] = print,
) -> tuple[list[dict], list[str]]:
    from evals.judge import judge_scenario

    records, incomplete = [], []
    thresholds = json.loads(THRESHOLDS_PATH.read_text())
    for i, scenario in enumerate(scenarios, 1):
        try:
            record = run_scenario(scenario, settings, llm_factory(scenario), prompt_version)
        except QuotaExhaustedError as exc:
            incomplete.append(f"stopped after {i - 1} of {len(scenarios)} scenarios: {exc}")
            log(f"[{i:>2}/{len(scenarios)}] {exc}")
            break
        if metrics:
            try:
                record["judge"] = judge_scenario(scenario, record["_responses"], metrics)
            except QuotaExhaustedError as exc:
                incomplete.append(f"LLM judge stopped at {scenario.id}: {exc}")
                metrics = {k: v for k, v in metrics.items() if k == "tool_correctness"}
                record["judge"] = {}
            for name, res in record["judge"].items():
                gate = thresholds["min"].get(name)
                if res["score"] is not None and gate is not None and res["score"] < gate:
                    record["failures"].append(f"low_{name}")
        record.pop("_responses")
        status = "FAIL " + ",".join(record["failures"]) if record["failures"] else "pass"
        log(f"[{i:>2}/{len(scenarios)}] {scenario.id:<6} {scenario.category:<15} {status}")
        records.append(record)
    return records, incomplete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-judged response_quality metric")
    parser.add_argument("--only", help="comma-separated scenario ids or categories")
    parser.add_argument("--limit", type=int, help="only run the first N scenarios")
    parser.add_argument("--prompt-version", help="override PROMPT_VERSION for this run")
    parser.add_argument("--update-baseline", action="store_true", help="save this run as the baseline")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)

    if args.prompt_version:
        os.environ["PROMPT_VERSION"] = args.prompt_version
    settings = get_settings()
    from hragent.llm import GroqClient
    from evals.judge import build_metrics

    agent_llm = GroqClient(settings)
    use_judge = not args.no_judge
    metrics = build_metrics(settings, use_llm_judge=use_judge)
    scenarios = select(load_scenarios(), args.only, args.limit)
    thresholds = json.loads(THRESHOLDS_PATH.read_text())

    records, incomplete = evaluate(scenarios, settings, lambda _s: agent_llm, settings.prompt_version, metrics)
    summary = aggregate(records)
    full_run = not args.only and not args.limit
    baseline = (
        json.loads(BASELINE_PATH.read_text())
        if BASELINE_PATH.exists() and not args.update_baseline and full_run
        else None
    )
    decision, reasons = decide(summary, baseline, thresholds)
    if incomplete:
        decision, reasons = "NO-GO", [f"evaluation incomplete — {r}" for r in incomplete] + reasons

    report = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "agent_model": agent_llm.model,
        "judge_model": settings.judge_model if use_judge else None,
        "prompt_version": settings.prompt_version,
        "n_scenarios": len(records),
        "summary": summary,
        "by_category": by_category(records),
        "baseline_summary": baseline["summary"] if baseline else None,
        "thresholds": {k: v for k, v in thresholds.items() if not k.startswith("_")},
        "decision": decision,
        "reasons": reasons,
        "cases": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, args.output_dir / "latest.md")
    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Baseline saved to {BASELINE_PATH.relative_to(PROJECT_ROOT)}")

    print("\n" + "\n".join(f"  {k:<24} {_fmt(v)}" for k, v in summary.items()))
    print(f"\nRelease decision: {decision}")
    for r in reasons:
        print(f"  - {r}")
    if os.getenv("GITHUB_ACTIONS"):
        line = " · ".join(f"{k}={_fmt(v)}" for k, v in summary.items() if v is not None and k not in INFO_METRICS)
        print(f"::notice title=Release decision: {decision}::{line}")
        for r in reasons[:9]:
            print(f"::warning title=Gate failed::{r}")
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:900]
        if os.getenv("GITHUB_ACTIONS"):
            print(f"::error title=Evaluation crashed::{message}")
        raise
