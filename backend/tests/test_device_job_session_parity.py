"""A device job session is set up like a terminal session.

Without this, a device run stops at Tests first: every Write is ``repository_root_unknown`` because only the
interactive launcher reports its repository, and the device turn starts unbound to its run. Here a device job
session goes through the real HTTP endpoints with a real device grant:

- ``sessions/register`` with the job's run header binds the session to the run at registration (no
  ``workflow_select``), under the attach rule; a run the user may not act on, or an unknown one, refuses it;
- ``sessions/repository`` binds the job folder's repository only when its remote is the run's repository on the
  Workspace's connection and its root lies inside the device's allowed folders;
- then B's Tests first (tests written, run, red) and Implement (the code changed, the confirmed test protected, the
  suite green) pass on that session.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from app.models import ToolCall, WorkflowRun
from app.services.agent_gateway.policy import load_workspace_policy
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.workflow_runs.gateway_tests import record_gateway_tests
from app.services.workflow_runs.octryx.stop import run_stop
from app.services.workflow_runs.records import active_run_for_session
from app.time_utils import utc_now
from tests.device_job_session_parity_support import (  # noqa: F401
    CONFIRMED,
    GATEWAY,
    TOTALS_TEST,
    _b_at_tests_first,
    _binding,
    _call,
    _device,
    _gateway,
    _headers,
    _register,
    _server_pipeline,
)
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture

FIXED = "def round_total(value: float) -> int:\n    return int(value + 0.5)\n"


def _pytest_output(working_copy: Path) -> str:
    done = subprocess.run([sys.executable, "-m", "pytest", "-rA", "-p", "no:cacheprovider", "-o", "addopts=",
                           CONFIRMED], cwd=working_copy, capture_output=True, text=True, timeout=120)
    return done.stdout


@pytest.mark.asyncio
async def test_a_device_job_session_is_bound_at_registration_and_runs_bs_tests_first_and_implement(
        client, auth_headers, db, systems):  # noqa: F811 - the imported fixture
    project, run_id, working_copy = await _b_at_tests_first(client, auth_headers, db, systems)
    admin = await admin_user(db)
    token = await _device(db, admin, [str(working_copy.parent)])
    headers = _headers(token, project.id, run_id)

    # Registration binds the session to the job's run and answers with its contract (no workflow_select).
    registered = await _register(client, headers)
    assert registered["status"] == 200, registered
    assert registered["workflow_run_attach"] == {"state": "attached"}
    assert registered["workflow_run"]["run"]["id"] == run_id
    assert registered["workflow_run"]["phase"]["node_id"] == "tests_first"
    gateway = await _gateway(db, headers)
    assert (await active_run_for_session(db, gateway.id)).id == run_id

    # The job folder's repository: the run's repository on the Workspace's connection, inside the allowed folders.
    bound = await client.post(f"{GATEWAY}/repository", headers=headers, json=_binding(str(working_copy)))
    assert bound.status_code == 200 and bound.json()["state"] == "bound", bound.text
    await db.refresh(gateway)
    assert gateway.metadata_["repository_binding"]["root"] == str(working_copy)

    key = headers["X-Octryx-Session"]
    policy = (await load_workspace_policy(db, project.id)).policy

    async def facts(**extra) -> dict:
        """What the launcher reports for the pass its contract names (``run_contract.facts``)."""
        current = await db.get(WorkflowRun, run_id)
        reported = {"node_id": current.current_node_id, "entry": current.node_state.get("entry"), **extra}
        if (working_copy / CONFIRMED).exists():
            content = (working_copy / CONFIRMED).read_bytes()
            reported.update(confirmed_test_digests={CONFIRMED: "sha256:" + hashlib.sha256(content).hexdigest()},
                            checked_files=[CONFIRMED])
        return {"workflow_run_facts": reported}

    async def pre_tool_use(tool: str, *, exists: bool = True, **tool_input) -> dict:
        hook = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(working_copy),
                "tool_input": tool_input, **await facts(target_exists=exists)}
        return await decide_tool_check(db, session=gateway, session_key=key, policy=policy, hook_input=hook)

    async def stop(rows: list[ToolCall]) -> dict:
        for row in rows:
            db.add(row)
        await db.flush()
        assert await record_gateway_tests(db, session_id=gateway.id, policy=policy, tool_calls=rows)
        answer = await run_stop(db, session=gateway, hook_input=await facts(), tool_calls=rows,
                                test_prefixes=(("pytest",),))
        await db.commit()
        return answer

    # Tests first: the test file is written (no repository_root_unknown), the tests run and fail on the assertion.
    test_path = str(working_copy / CONFIRMED)
    written = await pre_tool_use("Write", exists=False, file_path=test_path, content=TOTALS_TEST)
    assert written["decision"] == "allow", written
    outside = await pre_tool_use("Write", exists=False, file_path=str(working_copy / "pay" / "totals.py"),
                                 content=FIXED)
    # Only test files here: by default logged, not refused (``path_rules: strict`` refuses).
    assert (outside["decision"], outside["reason"]) == ("allow", "allowed_by_default")
    assert (await pre_tool_use("Bash", command=f"pytest -v {CONFIRMED}"))["decision"] == "allow"
    (working_copy / CONFIRMED).write_text(TOTALS_TEST)
    red = _pytest_output(working_copy)
    assert "FAILED" in red
    at = utc_now() + timedelta(seconds=5)
    answer = await stop([_call(gateway, "Write", at=at, file_path=test_path),
                         _call(gateway, "Bash", at=at + timedelta(seconds=1), ok=False, command=f"pytest -v {CONFIRMED}",
                               excerpt=red)])
    assert answer["state"] == "passed", answer
    run = await db.get(WorkflowRun, run_id)
    assert run.gate_results["red"]["state"] == "passed", run.gate_results["red"]["results"][0].get("detail")
    assert run.current_node_id == "implement"

    # Implement: the code changes, the confirmed test is protected, the suite goes green.
    edited = await pre_tool_use("Edit", file_path=str(working_copy / "pay" / "totals.py"), old_string="int(value)",
                                new_string="int(value + 0.5)")
    assert edited["decision"] == "allow", edited
    protected = await pre_tool_use("Edit", file_path=test_path, old_string="3", new_string="2")
    assert (protected["decision"], protected["reason"]) == ("deny", "confirmed_test_protected")
    (working_copy / "pay" / "totals.py").write_text(FIXED)
    green = _pytest_output(working_copy)
    assert "PASSED" in green and "FAILED" not in green
    at = utc_now() + timedelta(seconds=10)
    answer = await stop([_call(gateway, "Edit", at=at, file_path=str(working_copy / "pay" / "totals.py")),
                         _call(gateway, "Bash", at=at + timedelta(seconds=1), command=f"pytest -v {CONFIRMED}",
                               excerpt=green)])
    assert answer["state"] == "passed", answer
    run = await db.get(WorkflowRun, run_id)
    assert run.gate_results["green"]["state"] == "passed", [
        (item["type"], item["outcome"], item.get("detail")) for item in run.gate_results["green"]["results"]]
    assert run.current_node_id != "implement"
