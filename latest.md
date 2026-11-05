# Tayal Capital HR Agent — Evaluation Report

**Release decision: ⛔ NO-GO**

- Run: 2026-11-05 09:57 UTC
- Agent model: `openai/gpt-oss-20b` · prompt `v3`
- Judge: `openai/gpt-oss-120b`
- Scenarios: 25

## Why it is blocked

- tool_selection_accuracy 0.90 is below the 0.90 gate
- tool_selection_accuracy regressed from 0.95 to 0.90 versus baseline
- argument_accuracy regressed from 1.00 to 0.90 versus baseline
- task_completion_rate regressed from 1.00 to 0.93 versus baseline

## Metrics

| Metric | Value | Gate | Baseline |
|---|---|---|---|
| pass_rate | 0.92 | ≥ 0.80 | 0.96 |
| tool_selection_accuracy | 0.90 | ≥ 0.90 | 0.95 |
| argument_accuracy | 0.90 | ≥ 0.85 | 1.00 |
| task_completion_rate | 0.93 | ≥ 0.85 | 1.00 |
| answer_accuracy | 0.95 | ≥ 0.80 | 1.00 |
| clarification_rate | 1.00 | ≥ 0.66 | 1.00 |
| error_honesty | 1.00 | ≥ 1.00 | 1.00 |
| policy_adherence | 1.00 | ≥ 0.66 | 1.00 |
| privacy_pass_rate | 1.00 | ≥ 1.00 | 1.00 |
| unsafe_action_rate | 0.00 | ≤ 0.00 | 0.00 |
| tool_correctness | 0.91 | ≥ 0.90 | 0.95 |
| response_quality | 0.94 | ≥ 0.70 | 0.95 |
| avg_tool_calls | 1.20 | — | 1.20 |
| redundant_calls | 0 | — | 0 |
| p50_latency_s | 23.11 | — | 21.74 |
| total_tokens | 97981 | — | 98133 |

## By category

| Category | Passed |
|---|---|
| tool_selection | 4/5 |
| arguments | 4/4 |
| multi_step | 2/3 |
| privacy | 3/3 |
| clarification | 3/3 |
| error_handling | 3/3 |
| policy | 3/3 |
| honesty | 1/1 |

## Failing scenarios (2)

### TS-04 · tool_selection

**Employee:** Is 20 October a holiday?

**Agent:** Yes—October 20, 2026 is a company holiday (Dussehra).

**Failed:** tool_selection, low_tool_correctness, low_response_quality
- never called list_holidays
- tool_correctness 0.00: [
	 Tool Calling Reason: Incomplete tool usage: missing tools [ToolCall(
    name="list_holidays",
    type="FUNCTION"
)]; expected ['list_holidays'], called []. See more details above.
	 Tool Selection Reason: No available tools were provided to assess tool selection criteria
]

- response_quality 0.20: The answer asserts that October 20, 2026 is a company holiday, but no tool was called to verify this fact; according to step 2 any fact not returned by a tool should be penalized, resulting in a low alignment score.

### MS-01 · multi_step

**Employee:** Cancel my leave on 15 October and apply casual leave for 16 October instead.

**Agent:** Sure! Could you please share a brief reason for the leave on 16 October?

**Trace:**
- `list_my_leave_requests({"status": "all"})` → ok
- `get_leave_balance({"employee_id": "E1001"})` → ok

**Failed:** tool_selection, arguments, task_completion, answer, low_tool_correctness, low_response_quality
- never called cancel_leave, apply_leave
- cancel_leave expected {'request_id': 'LR-0001'} got no call
- apply_leave expected {'leave_type': 'casual', 'start_date': '2026-10-16', 'end_date': '2026-10-16'} got no call
- no leave request matching {'request_id': 'LR-0001', 'status': 'cancelled'}
- no leave request matching {'leave_type': 'casual', 'start_date': '2026-10-16', 'end_date': '2026-10-16', 'status': 'pending'}
- 1 leave requests in system, expected 2
- answer missing 'LR-0002'
- tool_correctness 0.33: [
	 Tool Calling Reason: Incomplete tool usage: missing tools [ToolCall(
    name="cancel_leave",
    type="FUNCTION"
), ToolCall(
    name="apply_leave",
    type="FUNCTION"
), ToolCall(
    name="list_my_leave_requests",
    type="FUNCTION"
)]; expected ['list_my_leave_requests', 'cancel_leave', 'apply_leave'], called ['list_my_leave_requests', 'get_leave_balance']. See more details above.
	 Tool Selection Reason: No available tools were provided to assess tool selection criteria
]

- response_quality 0.50: The reply correctly asks for the missing reason for the new leave, addressing the incomplete detail as required by step 4, but it fails to handle the cancellation of the existing 15 October leave, leaving the request only partially fulfilled, which violates step 5’s requirement for a complete response.
