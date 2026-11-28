"""Numeric cron weekdays of a registered schedule keep APScheduler's numbering (0 = Monday)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.scheduler.coordination.fingerprint import ScheduleRecord
from app.scheduler.dispatch.registration import SchedulerRegistrationMixin


@pytest.mark.parametrize("owner", ["task", "scheduler"])
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 9 * * 0-4", ["Mon", "Tue", "Wed", "Thu", "Fri", "Mon"]),
        ("0 9 * * 0", ["Mon", "Mon", "Mon", "Mon", "Mon", "Mon"]),
        ("0 9 * * mon-fri", ["Mon", "Tue", "Wed", "Thu", "Fri", "Mon"]),
    ],
)
def test_registered_jobs_keep_apscheduler_weekday_numbers(owner, expression, expected):
    registration = SchedulerRegistrationMixin()
    registration.scheduler = Mock()
    registration.run_task_now = Mock()
    registration._loaded_task_ids = set()
    registration._register_job(
        ScheduleRecord(owner, "schedule-1", expression, "task-1", "Weekday schedule", "fingerprint")
    )
    registration.scheduler.add_job.assert_called_once()
    trigger = registration.scheduler.add_job.call_args.kwargs["trigger"]
    # Registration uses the server zone. Pin it only for the reproducible test.
    trigger.timezone = UTC
    now, previous, days = datetime(2026, 10, 4, 8, tzinfo=UTC), None, []
    for _ in range(len(expected)):
        fire = trigger.get_next_fire_time(previous, now)
        days.append(fire.strftime("%a"))
        previous, now = fire, fire + timedelta(seconds=1)
    assert days == expected
