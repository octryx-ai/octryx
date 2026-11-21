"""Integration: both submit paths hand the actual caller to the phase output, never the requester."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import User

pytestmark = pytest.mark.asyncio


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, db, run, tool, raw, **kwargs):
        self.calls.append({"tool": tool, **kwargs})
        return {"state": "recorded", "version": 1, "hash": "sha256:x"}


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def test_the_chat_tool_hands_the_actual_user_to_a_test_contract_submit(db, monkeypatch):
    from app.services.workflow_runs import phase_outputs, records
    from app.tools.workflow_outputs import SubmitTestContractTool

    user = await _admin(db)
    run = SimpleNamespace(status="running")
    recorder = _Recorder()

    async def active_run(_db, _session_id):
        return run

    async def lock(_db, locked):
        return locked

    monkeypatch.setattr(records, "active_run_for_session", active_run)
    monkeypatch.setattr(records, "lock_run", lock)
    monkeypatch.setattr(phase_outputs, "submit_output", recorder)
    context = SimpleNamespace(db=db, session_id="s-1", user_id=user.id, request_id="r-1", turn_tool_history=[])

    answer = await SubmitTestContractTool().execute({"criteria": []}, context)

    assert answer["status"] == "recorded"
    # The caller's session travels too: a parallel_work item records its result on its own item.
    assert recorder.calls == [{"tool": "submit_test_contract", "principal": user, "session_id": "s-1"}]


async def test_the_mcp_submit_hands_the_actual_user_to_the_phase_output(db, monkeypatch):
    from app.services import mcp_workflow_run_session as mcp_session
    from app.services import mcp_workflow_run_tools as mcp
    from app.services.workflow_runs import access, phase_outputs, records

    user = await _admin(db)
    run = SimpleNamespace(project_id="ws-1", status="running")
    recorder = _Recorder()

    async def gateway(*_args, **_kwargs):
        return SimpleNamespace(id="g-1")

    async def active_run(_db, _session_id):
        return run

    async def write_access(*_args, **_kwargs):
        return "write"

    async def contract(*_args, **_kwargs):
        return {"phase": {"tools": {"allow": ["submit_test_contract"], "deny": []}}}

    async def lock(_db, locked):
        return locked

    monkeypatch.setattr(mcp, "_gateway", gateway)
    monkeypatch.setattr(mcp, "active_run_for_session", active_run, raising=False)
    monkeypatch.setattr(records, "active_run_for_session", active_run)
    monkeypatch.setattr(mcp_session, "run_contract", contract, raising=False)
    monkeypatch.setattr(access, "run_access", write_access)
    monkeypatch.setattr(records, "lock_run", lock)
    monkeypatch.setattr(phase_outputs, "submit_output", recorder)

    answer = await mcp._submit_phase_output(db, "submit_test_contract", caller=SimpleNamespace(), user=user,
                                            workspace_id="ws-1", arguments={"criteria": []})

    assert answer["state"] == "recorded"
    # The gateway session is the caller's session.
    assert recorder.calls == [{"tool": "submit_test_contract", "principal": user, "session_id": "g-1"}]
