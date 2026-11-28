"""Shared helpers for the test_workspace_preparation_* modules."""

from __future__ import annotations

import sys

import pytest

from app.services.agent_gateway.policy import load_workspace_policy
from app.services.workflow_runs.gateway_tests import record_gateway_tests
from app.services.workflow_runs.octryx.stop import run_stop
from tests.device_job_session_parity_support import (
    GATEWAY,
    _b_at_tests_first,
    _binding,
    _device,
    _gateway,
    _headers,
    _register,
)
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture


async def _device_at_tests_first(client, auth_headers, db, systems):  # noqa: F811
    project, run_id, working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    token = await _device(db, await admin_user(db), [str(working_copy.parent)])
    headers = _headers(token, project.id, run_id)
    assert (await _register(client, headers))["status"] == 200
    bound = await client.post(f"{GATEWAY}/repository", headers=headers, json=_binding(str(working_copy)))
    assert bound.status_code == 200, bound.text
    gateway = await _gateway(db, headers)
    policy = (await load_workspace_policy(db, project.id)).policy
    return run_id, working_copy, gateway, policy, headers


async def _stop(db, gateway, policy, rows) -> dict:
    for row in rows:
        db.add(row)
    await db.flush()
    await record_gateway_tests(db, session_id=gateway.id, policy=policy, tool_calls=rows)
    answer = await run_stop(db, session=gateway, hook_input={}, tool_calls=rows, test_prefixes=(
        ("pytest",), ("python3", "-m", "pytest")))
    await db.commit()
    return answer


SHIM = f"mkdir -p .tools && printf '#!/bin/sh\\nexec {sys.executable} \"$@\"\\n' > .tools/python && chmod +x .tools/python"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
