from evals.scorers import args_match, contains


def test_indian_number_formats_match():
    assert contains("Net pay was ₹1,11,800.", "111800")
    assert contains("Net pay was 111,800", "111800")
    assert not contains("Total 2026 days", "6")
    assert contains("You have 6 casual leaves", "6")


def test_args_normalised():
    assert args_match({"leave_type": "casual", "start_date": "2026-10-12"}, {"leave_type": "CL", "start_date": "2026-10-12", "reason": "x"})
    assert args_match({"category": ["leave", "other"]}, {"category": "Other"})
    assert not args_match({"start_date": "2026-10-12"}, {"start_date": "2026-10-13"})
    assert not args_match({"month": "2026-09"}, {})
