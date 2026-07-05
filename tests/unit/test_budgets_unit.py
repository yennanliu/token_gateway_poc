"""Unit test for the budget month-boundary helper (pure)."""

from datetime import datetime, timezone

from gateway import budgets


def test_month_start_normalizes_to_first_midnight_utc():
    now = datetime(2026, 7, 5, 13, 47, 30, tzinfo=timezone.utc)
    start = budgets._month_start(now)
    assert start == datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
