"""Every phase check of workflows A–E is satisfiable on an octryx device job, and only by recorded tool calls."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import Session
from app.models.runtime.secure_work import WorkItem
from app.services.agent_gateway.read_evidence import native_read_use, read_target
from app.services.mcp_run_work_item import run_bound_work_tool, run_work_item
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_runtime_evidence_support import (  # noqa: F401
    DEVICE_SCOPES,
    ROOT,
    _caller,
    _device_session,
    _native,
    _one_phase,
    _run_with_session,
    _server_pipeline,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


def test_the_read_target_is_computed_on_the_server_from_the_hook_payload():
    session = Session(metadata_={"repository_binding": {"root": ROOT}})

    def target(tool: str, tool_input: dict, cwd: str = ROOT) -> dict:
        return read_target(session, {"tool_name": tool, "tool_input": tool_input, "cwd": cwd})

    assert target("Read", {"file_path": f"{ROOT}/textkit/core.py"}) == {
        "tool": "Read", "in_root": True, "path": "textkit/core.py"}
    assert target("Read", {"file_path": "textkit/core.py"})["path"] == "textkit/core.py"
    assert target("Grep", {"pattern": "def wrap"})["in_root"] is True
    assert target("Glob", {"pattern": "**/*.py", "path": f"{ROOT}/textkit"})["path"] == "textkit"
    for tool, tool_input, cwd in (("Read", {"file_path": "/etc/passwd"}, ROOT),
                                  ("Read", {"file_path": "../other/secret.py"}, ROOT),
                                  ("Read", {"file_path": "~/notes.md"}, ROOT),
                                  ("Grep", {"pattern": "x"}, "/work"),
                                  ("Glob", {"pattern": "../**/*.py"}, ROOT),
                                  ("Read", {"file_path": f"{ROOT}-evil/core.py"}, ROOT)):
        assert target(tool, tool_input, cwd)["in_root"] is False, (tool, tool_input, cwd)
    assert read_target(Session(metadata_={}), {"tool_name": "Read", "tool_input": {"file_path": f"{ROOT}/a.py"},
                                               "cwd": ROOT})["in_root"] is False
    assert read_target(session, {"tool_name": "Bash", "tool_input": {"command": "cat a.py"}, "cwd": ROOT})[
        "read_tool"] == "read_workspace_file"
    assert read_target(session, {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "cwd": ROOT}) is None


@pytest.mark.asyncio
async def test_a_native_read_counts_only_with_the_hook_the_transcript_and_a_path_in_the_repository(db):
    admin = await admin_user(db)
    gateway, _key = await _device_session(db, admin, await seed_workspace(db))
    recorded = await _native(db, gateway, "Read", {"file_path": f"{ROOT}/textkit/core.py"})
    assert native_read_use(recorded[0]).succeeded is True
    assert native_read_use(recorded[0]).name == "read_workspace_file"
    assert native_read_use((await _native(db, gateway, "Grep", {"pattern": "wrap"}))[0]).name == "grep_workspace"

    claimed = await _native(db, gateway, "Read", {"file_path": f"{ROOT}/textkit/core.py"}, hook=None)
    hook_only = await _native(db, gateway, "Read", {"file_path": f"{ROOT}/textkit/core.py"}, transcript=False)
    outside = await _native(db, gateway, "Read", {"file_path": "/etc/hosts"})
    failed = await _native(db, gateway, "Read", {"file_path": f"{ROOT}/missing.py"}, hook="PostToolUseFailure")
    for rows in (claimed, hook_only, outside, failed):
        assert native_read_use(rows[0]).succeeded is False


@pytest.mark.asyncio
async def test_a_device_session_reads_only_its_runs_own_work_item_without_work_manage(db, monkeypatch):
    run, gateway, key, workspace_id = await _run_with_session(db, _one_phase("feature-delivery-tdd", "clarify"),
                                                              item=True)
    admin = await admin_user(db)
    assert "work:manage" not in DEVICE_SCOPES and run_bound_work_tool("work_item_context", DEVICE_SCOPES)
    assert run_bound_work_tool("work_item_note", DEVICE_SCOPES) and not run_bound_work_tool("work_item_find",
                                                                                          DEVICE_SCOPES)
    assert not run_bound_work_tool("work_item_create", ("workflow:read",))
    caller = _caller(admin, workspace_id, key)
    for reference in ("BRD-7", run.work_item_id, ""):
        item = await run_work_item(db, caller=caller, user=admin, workspace_id=workspace_id, requested=reference)
        assert item.id == run.work_item_id

    other = WorkItem(source_type="jira", source_instance="t", source_key="BRD-8", title="x", project_id=workspace_id)
    db.add(other)
    await db.flush()
    refusals = [
        (caller, admin, "BRD-8"),
        (_caller(admin, workspace_id, None), admin, "BRD-7"),
        (_caller(admin, workspace_id, str(uuid.uuid4())), admin, "BRD-7"),
    ]
    outsider = await fetch_user(db, await seed_member(db, workspace_id=await seed_workspace(db), role="member"))
    refusals.append((_caller(outsider, workspace_id, key), outsider, "BRD-7"))
    for refused_caller, user, reference in refusals:
        with pytest.raises(HTTPException) as refused:
            await run_work_item(db, caller=refused_caller, user=user, workspace_id=workspace_id, requested=reference)
        assert refused.value.status_code == 403

    import app.services.mcp_knowledge_protocol as protocol

    seen = []

    async def run_bound(found_caller, tool_name, arguments):
        seen.append((found_caller.scopes, tool_name, arguments))
        return {"work_item": {"key": "BRD-7"}}

    monkeypatch.setattr(protocol, "_authenticated_context", lambda ctx: (admin.id, None, "device-grant", DEVICE_SCOPES))
    monkeypatch.setattr(protocol, "call_run_bound_work_tool", run_bound)
    assert await protocol._call_secure_work_tool(None, "work_item_context", {"work_item": "BRD-7"}) == {
        "work_item": {"key": "BRD-7"}}
    assert seen == [(DEVICE_SCOPES, "work_item_context", {"work_item": "BRD-7"})]
    for tool in ("work_item_find", "work_item_transition"):
        with pytest.raises(HTTPException) as refused:
            await protocol._call_secure_work_tool(None, tool, {"work_item": "BRD-7"})
        assert refused.value.status_code == 403 and "work:manage" in refused.value.detail


@pytest.mark.asyncio
async def test_a_run_creates_tickets_in_its_workspace_only_while_its_phase_allows_it(db):
    from app.services.mcp_run_work_item import _phase_allows, _write

    definition = _one_phase("spec-writing", "split")
    phase = definition["nodes"][1]["config"]
    phase.pop("output")
    phase["workflow_contract"]["checks"] = [{"type": "tool_called", "params": {"tools": ["work_item_context"]},
                                             "blocking": True, "description": "The epic was read"}]
    phase["tool_policy"]["allowlist"] += ["work_item_create", "work_item_note"]
    run, _gateway, _key, workspace_id = await _run_with_session(db, definition, item=True)
    member = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    item = await db.get(WorkItem, run.work_item_id)
    assert await _phase_allows(db, run, "work_item_create") and await _phase_allows(db, run, "work_item_note")
    assert not await _phase_allows(db, run, "work_item_transition")
    created = await _write(db, run, item, member, "work_item_create",
                           {"title": "Packmate T11: templates", "description": "AC1", "project_id": "elsewhere"})
    ticket = await db.get(WorkItem, created["id"])
    assert (ticket.project_id, ticket.source_type, ticket.title) == (workspace_id, "platform", "Packmate T11: templates")
    again = await _write(db, run, item, member, "work_item_create", {"title": "Packmate T11: templates"})
    assert again["already_existed"] is True and again["id"] == created["id"]
    await _write(db, run, item, member, "work_item_note", {"note": "Tickets: T11"})
    assert item.source_fields_json["platform_notes"][-1]["note"] == "Tickets: T11"

    drafting, *_ = await _run_with_session(db, _one_phase("spec-writing", "interview"))
    assert not await _phase_allows(db, drafting, "work_item_create")
