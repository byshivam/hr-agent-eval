import pytest

from hragent.hr_system import HRSystem, ToolError


@pytest.fixture
def hr():
    return HRSystem(current_user="E1001")


def test_working_days_skip_weekends_and_holidays(hr):
    from datetime import date
    assert hr.working_days(date(2026, 10, 19), date(2026, 10, 23)) == 4  # Dussehra on the 20th
    assert hr.working_days(date(2026, 10, 10), date(2026, 10, 11)) == 0  # weekend


def test_apply_and_cancel_round_trip(hr):
    res = hr.apply_leave("CL", "2026-10-12", "2026-10-13")
    assert res["status"] == "pending" and res["working_days_deducted"] == 2
    assert hr.balances["E1001"]["casual"] == 4
    hr.cancel_leave(res["request_id"])
    assert hr.balances["E1001"]["casual"] == 6


@pytest.mark.parametrize(
    "args, code",
    [
        (("casual", "2026-10-07", "2026-10-07"), "POLICY_VIOLATION"),   # same day
        (("casual", "2026-10-12", "2026-10-16"), "POLICY_VIOLATION"),   # > 3 days
        (("earned", "2026-10-08", "2026-10-08"), "POLICY_VIOLATION"),   # < 7 days notice
        (("sick", "2026-09-01", "2026-09-01"), "POLICY_VIOLATION"),     # too far back
        (("casual", "2026-10-10", "2026-10-11"), "NO_WORKING_DAYS"),
        (("vacation", "2026-10-12", "2026-10-12"), "INVALID_LEAVE_TYPE"),
        (("casual", "12/10/2026", "12/10/2026"), "INVALID_DATE"),
    ],
)
def test_policy_rules_enforced(hr, args, code):
    with pytest.raises(ToolError) as err:
        hr.apply_leave(*args)
    assert err.value.code == code


def test_insufficient_balance():
    hr = HRSystem(current_user="E1002")
    with pytest.raises(ToolError) as err:
        hr.apply_leave("casual", "2026-10-12", "2026-10-13")
    assert err.value.code == "INSUFFICIENT_BALANCE"


def test_overlap_rejected(hr):
    hr.apply_leave("casual", "2026-10-12", "2026-10-12")
    with pytest.raises(ToolError) as err:
        hr.apply_leave("sick", "2026-10-12", "2026-10-12")
    assert err.value.code == "OVERLAP"


def test_backend_blocks_other_employees(hr):
    with pytest.raises(ToolError) as err:
        hr.get_payslip("2026-09", employee_id="E1002")
    assert err.value.code == "PERMISSION_DENIED"
    with pytest.raises(ToolError):
        hr.get_leave_balance(employee_id="E1003")


def test_directory_returns_public_fields_only(hr):
    match = hr.lookup_colleague("ananya")["matches"][0]
    assert set(match) == {"employee_id", "name", "title", "department", "work_email", "manager_id"}


def test_fault_injection(hr):
    hr.failing_tools = {"apply_leave": "SERVICE_UNAVAILABLE"}
    with pytest.raises(ToolError) as err:
        hr.apply_leave("casual", "2026-10-12", "2026-10-12")
    assert err.value.code == "SERVICE_UNAVAILABLE"
    assert hr.leave_requests == []


def test_policy_search_finds_cited_sections():
    from hragent.config import get_settings
    from hragent.policies import search

    hits = search(get_settings().policies_dir, "paternity leave days")
    assert hits[0]["section_id"] == "LV-07"
    assert search(get_settings().policies_dir, "when is salary credited")[0]["section_id"] == "PB-01"
