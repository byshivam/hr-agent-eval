"""Load evaluation scenarios and build the HR backend each one starts from."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from hragent.hr_system import HRSystem

SCENARIOS_PATH = Path(__file__).parent / "scenarios.jsonl"
CATEGORIES = (
    "tool_selection", "arguments", "multi_step", "privacy",
    "clarification", "error_handling", "policy", "honesty",
)


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    turns: list[str]
    expect: dict
    user: str = "E1001"
    setup: dict = field(default_factory=dict)
    description: str = ""

    def build_hr(self) -> HRSystem:
        hr = HRSystem(current_user=self.user)
        for req in self.setup.get("leave_requests", []):
            hr.add_leave_request(**req)
        hr.failing_tools = dict(self.setup.get("failing_tools", {}))
        return hr


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[Scenario]:
    scenarios = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row["category"] not in CATEGORIES:
            raise ValueError(f"line {n}: unknown category {row['category']!r}")
        scenarios.append(Scenario(**row))
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario ids")
    return scenarios
