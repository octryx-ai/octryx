from __future__ import annotations

from datetime import datetime

from app.services.secure_work.jira_values import parse_datetime


def test_offset_aware_timestamps_normalize_to_utc():
    # Jira sends local time with an offset; stored values are naive UTC.
    assert parse_datetime("2026-07-06T12:28:18.000+0200") == datetime(2026, 7, 6, 10, 28, 18)
    assert parse_datetime("2026-07-06T10:28:18Z") == datetime(2026, 7, 6, 10, 28, 18)


def test_naive_and_invalid_values():
    assert parse_datetime("2026-07-06T10:28:18") == datetime(2026, 7, 6, 10, 28, 18)
    assert parse_datetime("not-a-date") is None
    assert parse_datetime(None) is None
