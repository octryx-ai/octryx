"""A device phase turn that runs in circles is stopped at the model gateway (a model can echo the same
"SUCCESS ..." line a thousand times in an hour until the launcher's job limit ends it)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import ToolCall
from app.services.workflow_runs.octryx.run_guard import (
    CODE_AGENT_LOOP,
    REASON_AGENT_LOOP,
    device_loop_refusal,
    loop_kind,
    noop_shell,
)
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased


def _bash(command: str) -> tuple[str, dict]:
    return "Bash", {"command": command}


def test_only_printing_commands_are_no_ops():
    assert noop_shell(*_bash('echo "SUCCESS: Packmate checklist API implementation complete"'))
    assert noop_shell(*_bash("printf 'done\\n' && true"))
    assert not noop_shell(*_bash("echo x > SPEC.md"))
    assert not noop_shell(*_bash("echo $(rm -rf build)"))
    assert not noop_shell(*_bash(".venv/bin/python -m pytest -q"))
    assert not noop_shell("Read", {"file_path": "x"})


def test_six_of_the_last_eight_calls_printing_is_a_loop():
    work = [_bash(".venv/bin/python -m pytest -q"), ("Edit", {"file_path": "a.py", "old_string": "1"})]
    echoes = [_bash(f'echo "SUCCESS {n}"') for n in range(6)]
    assert loop_kind(work + echoes) == "noop"
    assert loop_kind(work + echoes[:4] + work) is None  # a summary echo or two between real work is fine


def test_the_same_call_four_times_is_a_loop():
    same = ("Read", {"file_path": "src/packmate/repository.py"})
    assert loop_kind([same, _bash("ls"), same, same]) is None
    assert loop_kind([same, _bash("ls"), same, same, same]) == "repeat"


@pytest.mark.asyncio
async def test_a_looping_phase_turn_pauses_the_run_and_every_further_model_request_is_refused(db):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    session_id = await main_session_id(db, run)
    assert run.status == "running"
    assert await device_loop_refusal(db, session_id) is None  # nothing done yet

    entered = utc_now().replace(tzinfo=None)
    run.node_state = {**dict(run.node_state or {}), "entered_at": (entered - timedelta(minutes=5)).isoformat()}
    for n in range(7):
        db.add(ToolCall(id=str(uuid.uuid4()), session_id=session_id, tool_name="Bash", status="success",
                        parameters={"input": {"command": f'echo "SUCCESS {n}"'}},
                        created_at=entered + timedelta(seconds=n)))
    await db.flush()

    assert await device_loop_refusal(db, session_id) == REASON_AGENT_LOOP
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "agent_loop")
    pause = run.node_state["pause"]
    assert pause["code"] == CODE_AGENT_LOOP and pause["resume"]["kind"] == "restart"
    assert "echo" in pause["message"]
    # The run view carries the code, so the card can say "repeated / only printed" instead of "runtime failed".
    from app.services.workflow_runs.views import _pause
    view = _pause(run)
    assert (view["code"], view["loop_kind"]) == (CODE_AGENT_LOOP, "noop")
    assert await device_loop_refusal(db, session_id) == REASON_AGENT_LOOP  # the device turn ends at once


def test_a_call_recorded_twice_counts_once():
    # A denied call is recorded as denied_by_policy and as error; two attempts are no loop.
    from app.services.workflow_runs.octryx.run_guard import once_per_call

    def row(use_id, status, command=None):
        parameters = {"tool_use_id": use_id, **({"input": {"command": command}} if command else {})}
        return ToolCall(id=str(uuid.uuid4()), session_id="s", tool_name="Bash", status=status, parameters=parameters)

    test = ".venv/bin/python -m pytest -v tests/test_checklist_api.py 2>&1"
    rows = [row("a", "denied_by_policy", test), row("a", "error", test), row("b", "denied_by_policy", test),
            row("b", "error", test), row("c", "requested"), row("d", "requested")]
    calls = once_per_call(rows)
    assert calls == [("Bash", {"command": test}), ("Bash", {"command": test})]
    assert loop_kind(calls) is None


def test_joining_stderr_into_stdout_is_a_plain_command():
    from app.services.agent_gateway.command_strict import strict_argv

    assert strict_argv(".venv/bin/python -m pytest -v tests/x.py 2>&1") == [
        (".venv/bin/python", "-m", "pytest", "-v", "tests/x.py")]
    assert strict_argv("pytest 2>&1 > out") is None and strict_argv("pytest >out") is None
