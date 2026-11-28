"""Cases on the phone: read Work items and runs, steer an existing run; nothing else."""

from __future__ import annotations

import pytest

from app.services.mobile.session import phone_may_use


@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("GET", "/api/v1/secure-work/work-items", True),
    ("GET", "/api/v1/workflow-runs", True),
    ("GET", "/api/v1/workflow-runs/3f2a1b4c-0000-4000-8000-000000000001", True),
    ("POST", "/api/v1/workflow-runs/3f2a1b4c-0000-4000-8000-000000000001/actions", True),
    # A task's detail, its plans and an Epic's progress; every other per-item route stays off.
    ("GET", "/api/v1/secure-work/work-items/33c34a5b-561c-4de3-a13c-effdf315b5d6", True),
    ("GET", "/api/v1/secure-work/work-items/33c34a5b-561c-4de3-a13c-effdf315b5d6/change-plans", True),
    ("GET", "/api/v1/secure-work/work-items/33c34a5b-561c-4de3-a13c-effdf315b5d6/progress", True),
    ("POST", "/api/v1/secure-work/work-items/33c34a5b/progress", False),
    ("POST", "/api/v1/secure-work/work-items/33c34a5b/change-plans", False),
    ("GET", "/api/v1/secure-work/work-items/33c34a5b/coding-pipeline", False),
    ("POST", "/api/v1/secure-work/work-items/33c34a5b/transition", False),
    ("POST", "/api/v1/secure-work/work-items/33c34a5b/close", False),
    ("GET", "/api/v1/secure-work/work-items/33c34a5b/change-plans/x", False),
    # Starting a run for a task: the startable workflows, where it may run, the start.
    ("POST", "/api/v1/workflow-runs", True),
    ("GET", "/api/v1/workflow-runs/startable", True),
    ("GET", "/api/v1/workflow-runs/runtime-targets", True),
    # Off the phone: the limits, a new session, events, bindings, admin and write routes.
    ("PUT", "/api/v1/workflow-runs/limits", False),
    ("GET", "/api/v1/workflow-runs/limits", False),
    ("POST", "/api/v1/workflow-runs/startable", False),
    ("PUT", "/api/v1/workflow-runs", False),
    ("POST", "/api/v1/workflow-runs/3f2a1b4c/session", False),
    ("POST", "/api/v1/workflow-runs/3f2a1b4c/sessions", False),
    ("GET", "/api/v1/workflow-runs/3f2a1b4c/events", False),
    ("POST", "/api/v1/secure-work/work-items", False),
    ("GET", "/api/v1/secure-work/work-items/x/lifecycle", False),
    ("GET", "/api/v1/admin/devices/login-validity", False),
])
def test_only_the_case_routes_reach_the_phone(method, path, allowed):
    assert phone_may_use(method, path) is allowed
