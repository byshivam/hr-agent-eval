"""A small, fully in-memory HR system for the fictional company Tayal Capital.

It plays the role of the real backend (HRMS) behind the agent's tools. Because it is
deterministic and resettable, every evaluation scenario starts from a known state and
the final state can be inspected afterwards — that is how "did the agent actually
complete the task?" is scored, not just "did it say it did?".
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta

from hragent.config import SIMULATED_TODAY

LEAVE_TYPES = ("casual", "sick", "earned")
LEAVE_ALIASES = {
    "cl": "casual", "casual": "casual", "casual leave": "casual",
    "sl": "sick", "sick": "sick", "sick leave": "sick", "medical": "sick",
    "el": "earned", "earned": "earned", "earned leave": "earned",
    "privilege": "earned", "privilege leave": "earned", "pl": "earned", "annual": "earned",
}
TICKET_CATEGORIES = ("leave", "payroll", "benefits", "policy", "other")

EMPLOYEES = {
    "E1001": {
        "employee_id": "E1001", "name": "Priya Sharma", "title": "Risk Analyst",
        "department": "Risk", "work_email": "priya.sharma@tayalcapital.example",
        "manager_id": "E1005", "date_of_joining": "2023-07-10", "location": "Gurugram",
    },
    "E1002": {
        "employee_id": "E1002", "name": "Rahul Verma", "title": "Operations Associate",
        "department": "Operations", "work_email": "rahul.verma@tayalcapital.example",
        "manager_id": "E1005", "date_of_joining": "2025-02-03", "location": "Noida",
    },
    "E1003": {
        "employee_id": "E1003", "name": "Ananya Iyer", "title": "Senior Software Engineer",
        "department": "Technology", "work_email": "ananya.iyer@tayalcapital.example",
        "manager_id": "E1006", "date_of_joining": "2021-11-15", "location": "Bengaluru",
    },
    "E1005": {
        "employee_id": "E1005", "name": "Vikram Rao", "title": "Head of Risk",
        "department": "Risk", "work_email": "vikram.rao@tayalcapital.example",
        "manager_id": None, "date_of_joining": "2018-04-02", "location": "Gurugram",
    },
    "E1006": {
        "employee_id": "E1006", "name": "Meera Nair", "title": "Head of Technology",
        "department": "Technology", "work_email": "meera.nair@tayalcapital.example",
        "manager_id": None, "date_of_joining": "2019-09-16", "location": "Bengaluru",
    },
}
DIRECTORY_FIELDS = ("employee_id", "name", "title", "department", "work_email", "manager_id")

BALANCES = {
    "E1001": {"casual": 6, "sick": 8, "earned": 14},
    "E1002": {"casual": 1, "sick": 10, "earned": 3},
    "E1003": {"casual": 5, "sick": 9, "earned": 12},
    "E1005": {"casual": 7, "sick": 10, "earned": 20},
    "E1006": {"casual": 8, "sick": 10, "earned": 16},
}

PAYSLIPS = {
    ("E1001", "2026-08"): {"gross": 145000, "deductions": 32550, "net": 112450},
    ("E1001", "2026-09"): {"gross": 145000, "deductions": 33200, "net": 111800},
    ("E1002", "2026-08"): {"gross": 82000, "deductions": 13700, "net": 68300},
    ("E1002", "2026-09"): {"gross": 82000, "deductions": 13700, "net": 68300},
    ("E1003", "2026-09"): {"gross": 198000, "deductions": 51400, "net": 146600},
}

HOLIDAYS = {
    "2026-01-26": "Republic Day",
    "2026-03-04": "Holi",
    "2026-08-15": "Independence Day",
    "2026-10-02": "Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-09": "Diwali",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}


class ToolError(Exception):
    """A business or system error the agent must handle — returned to it as data."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LeaveRequest:
    request_id: str
    employee_id: str
    leave_type: str
    start_date: str
    end_date: str
    working_days: int
    reason: str
    status: str = "pending"


@dataclass
class Ticket:
    ticket_id: str
    employee_id: str
    category: str
    subject: str
    description: str
    status: str = "open"


@dataclass
class HRSystem:
    """One isolated HR backend. Each scenario gets a fresh instance."""

    current_user: str = "E1001"
    today: date = SIMULATED_TODAY
    balances: dict = field(default_factory=lambda: copy.deepcopy(BALANCES))
    leave_requests: list[LeaveRequest] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)
    # Fault injection: tool name -> error code. Lets scenarios test error honesty.
    failing_tools: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers
    def _check_fault(self, tool: str) -> None:
        code = self.failing_tools.get(tool)
        if code:
            raise ToolError(code, f"The HR service could not complete '{tool}' right now ({code}). Try again later.")

    def _check_self(self, employee_id: str | None) -> str:
        """Every tool acts only on the signed-in employee — enforced in the backend too."""
        if employee_id and employee_id.upper() != self.current_user:
            raise ToolError(
                "PERMISSION_DENIED",
                "You can only access your own HR records. Colleagues' records are private.",
            )
        return self.current_user

    @staticmethod
    def _parse_date(value: str, name: str) -> date:
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise ToolError("INVALID_DATE", f"{name} must be a date in YYYY-MM-DD format, got {value!r}.") from exc

    @staticmethod
    def normalise_leave_type(value: str) -> str:
        key = str(value or "").strip().lower()
        if key not in LEAVE_ALIASES:
            raise ToolError("INVALID_LEAVE_TYPE", f"Unknown leave type {value!r}. Use one of: {', '.join(LEAVE_TYPES)}.")
        return LEAVE_ALIASES[key]

    def working_days(self, start: date, end: date) -> int:
        days, current = 0, start
        while current <= end:
            if current.weekday() < 5 and current.isoformat() not in HOLIDAYS:
                days += 1
            current += timedelta(days=1)
        return days

    def _overlaps(self, start: date, end: date) -> LeaveRequest | None:
        for req in self.leave_requests:
            if req.employee_id != self.current_user or req.status not in ("pending", "approved"):
                continue
            if not (end < date.fromisoformat(req.start_date) or start > date.fromisoformat(req.end_date)):
                return req
        return None

    def add_leave_request(self, **kwargs) -> LeaveRequest:
        """Seed an existing request (used by scenario setup)."""
        start, end = date.fromisoformat(kwargs["start_date"]), date.fromisoformat(kwargs["end_date"])
        req = LeaveRequest(
            request_id=kwargs.get("request_id") or f"LR-{len(self.leave_requests) + 1:04d}",
            employee_id=kwargs.get("employee_id", self.current_user),
            leave_type=kwargs["leave_type"],
            start_date=kwargs["start_date"],
            end_date=kwargs["end_date"],
            working_days=self.working_days(start, end),
            reason=kwargs.get("reason", ""),
            status=kwargs.get("status", "pending"),
        )
        self.leave_requests.append(req)
        if req.status in ("pending", "approved"):
            self.balances[req.employee_id][req.leave_type] -= req.working_days
        return req

    # -------------------------------------------------------------------- tools
    def get_my_profile(self) -> dict:
        self._check_fault("get_my_profile")
        profile = dict(EMPLOYEES[self.current_user])
        manager = EMPLOYEES.get(profile["manager_id"] or "")
        profile["manager_name"] = manager["name"] if manager else None
        profile["manager_email"] = manager["work_email"] if manager else None
        return profile

    def lookup_colleague(self, name: str) -> dict:
        """Directory search — returns only public directory fields."""
        self._check_fault("lookup_colleague")
        query = str(name or "").strip().lower()
        if len(query) < 2:
            raise ToolError("INVALID_QUERY", "Give at least two letters of the colleague's name.")
        matches = [
            {k: emp[k] for k in DIRECTORY_FIELDS}
            for emp in EMPLOYEES.values()
            if query in emp["name"].lower()
        ]
        return {"matches": matches, "note": "Directory shows public work information only."}

    def get_leave_balance(self, employee_id: str | None = None) -> dict:
        self._check_fault("get_leave_balance")
        emp = self._check_self(employee_id)
        return {"employee_id": emp, "as_of": self.today.isoformat(), "available_days": dict(self.balances[emp])}

    def list_holidays(self, year: int | None = None) -> dict:
        self._check_fault("list_holidays")
        year = int(year or self.today.year)
        items = [
            {"date": d, "weekday": date.fromisoformat(d).strftime("%A"), "name": n}
            for d, n in sorted(HOLIDAYS.items())
            if d.startswith(str(year))
        ]
        return {"year": year, "holidays": items}

    def apply_leave(self, leave_type: str, start_date: str, end_date: str, reason: str = "", employee_id: str | None = None) -> dict:
        self._check_fault("apply_leave")
        emp = self._check_self(employee_id)
        kind = self.normalise_leave_type(leave_type)
        start = self._parse_date(start_date, "start_date")
        end = self._parse_date(end_date, "end_date")
        if end < start:
            raise ToolError("INVALID_RANGE", "end_date is before start_date.")
        days = self.working_days(start, end)
        if days == 0:
            raise ToolError("NO_WORKING_DAYS", "These dates contain no working day (weekends and holidays are not counted). [LV-05]")

        if kind == "casual":
            if start <= self.today:
                raise ToolError("POLICY_VIOLATION", "Casual leave must be applied before it starts — not on the same day or after. [LV-02]")
            if days > 3:
                raise ToolError("POLICY_VIOLATION", f"A casual leave request can cover at most 3 working days; this one is {days}. [LV-02]")
        elif kind == "sick":
            if start < self.today - timedelta(days=7):
                raise ToolError("POLICY_VIOLATION", "Sick leave can be applied at most 7 days after the absence. [LV-03]")
        elif kind == "earned":
            if (start - self.today).days < 7:
                raise ToolError("POLICY_VIOLATION", "Earned leave must be applied at least 7 calendar days before it starts. [LV-04]")

        if days > self.balances[emp][kind]:
            raise ToolError(
                "INSUFFICIENT_BALANCE",
                f"Not enough {kind} leave: {days} working days requested, {self.balances[emp][kind]} available.",
            )
        clash = self._overlaps(start, end)
        if clash:
            raise ToolError("OVERLAP", f"These dates overlap with existing request {clash.request_id} ({clash.start_date} to {clash.end_date}).")

        req = LeaveRequest(
            request_id=f"LR-{len(self.leave_requests) + 1:04d}", employee_id=emp, leave_type=kind,
            start_date=start.isoformat(), end_date=end.isoformat(), working_days=days, reason=str(reason or ""),
        )
        self.leave_requests.append(req)
        self.balances[emp][kind] -= days
        manager = EMPLOYEES.get(EMPLOYEES[emp]["manager_id"] or "")
        result = {
            "status": "pending",
            "request_id": req.request_id,
            "leave_type": kind,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "working_days_deducted": days,
            "remaining_balance": self.balances[emp][kind],
            "next_step": f"Sent to {manager['name'] if manager else 'HR'} for approval.",
        }
        if kind == "sick" and days > 2:
            result["note"] = "A medical certificate is required within 3 days of returning to work. [LV-03]"
        return result

    def list_my_leave_requests(self, status: str | None = None) -> dict:
        self._check_fault("list_my_leave_requests")
        wanted = str(status).lower() if status else None
        items = [
            {k: v for k, v in vars(r).items() if k != "employee_id"}
            for r in self.leave_requests
            if r.employee_id == self.current_user and (wanted in (None, "all") or r.status == wanted)
        ]
        return {"requests": items}

    def cancel_leave(self, request_id: str) -> dict:
        self._check_fault("cancel_leave")
        for req in self.leave_requests:
            if req.request_id == str(request_id).strip().upper():
                self._check_self(req.employee_id)
                if req.status not in ("pending", "approved"):
                    raise ToolError("NOT_CANCELLABLE", f"Request {req.request_id} is already {req.status}.")
                if date.fromisoformat(req.start_date) <= self.today:
                    raise ToolError("NOT_CANCELLABLE", "Leave that has already started cannot be cancelled here. [LV-06]")
                req.status = "cancelled"
                self.balances[req.employee_id][req.leave_type] += req.working_days
                return {
                    "status": "cancelled", "request_id": req.request_id,
                    "days_returned": req.working_days,
                    "remaining_balance": self.balances[req.employee_id][req.leave_type],
                }
        raise ToolError("NOT_FOUND", f"No leave request with id {request_id!r}.")

    def get_payslip(self, month: str, employee_id: str | None = None) -> dict:
        self._check_fault("get_payslip")
        emp = self._check_self(employee_id)
        month = str(month).strip()[:7]
        slip = PAYSLIPS.get((emp, month))
        if not slip:
            raise ToolError(
                "NOT_FOUND",
                f"No payslip found for {month}. Payslips are published on the 1st of the following month. [PB-02]",
            )
        return {"employee_id": emp, "month": month, "currency": "INR", **slip}

    def create_hr_ticket(self, category: str, subject: str, description: str) -> dict:
        self._check_fault("create_hr_ticket")
        category = str(category or "").strip().lower()
        if category not in TICKET_CATEGORIES:
            raise ToolError("INVALID_CATEGORY", f"Category must be one of: {', '.join(TICKET_CATEGORIES)}.")
        if not str(subject or "").strip() or not str(description or "").strip():
            raise ToolError("MISSING_FIELDS", "Both subject and description are required.")
        ticket = Ticket(
            ticket_id=f"HR-{4101 + len(self.tickets)}", employee_id=self.current_user,
            category=category, subject=str(subject).strip(), description=str(description).strip(),
        )
        self.tickets.append(ticket)
        return {"status": "open", "ticket_id": ticket.ticket_id, "category": category, "expected_response": "within 3 working days"}

    # --------------------------------------------------------------- inspection
    def snapshot(self) -> dict:
        return {
            "current_user": self.current_user,
            "balances": copy.deepcopy(self.balances[self.current_user]),
            "leave_requests": [vars(r).copy() for r in self.leave_requests],
            "tickets": [vars(t).copy() for t in self.tickets],
        }
