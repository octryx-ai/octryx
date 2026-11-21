"""Shared helpers for the test_workflow_run_runtime_evidence_* modules."""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta

import pytest

from app.models import Session, ToolCall, User, WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.services.devices.contract import DEVICE_JOB_SCOPES
from app.services.mcp_governed_knowledge import McpCaller
from app.services.model_gateway.inbound.transcript_tools import upsert_gateway_tool_calls
from app.services.model_gateway.inbound.turn_delta import newest_turn
from app.services.workflow_runs.records import new_chat_session, start_run
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import admin_user, publish_phased

ROOT = "/work/textkit"


PREFIX = "mcp__octryx-knowledge__"


DEVICE_SCOPES = tuple(sorted(DEVICE_JOB_SCOPES | {"device:connect"}))


PREFIXES = (("pytest",),)


def _seed_node(key: str, node_id: str) -> dict:
    seed = next(item for item in seed_definitions() if item["key"] == key)
    return copy.deepcopy(next(node for node in seed["definition"]["nodes"] if node["id"] == node_id))


def _one_phase(key: str, phase_id: str, gate_id: str | None = None) -> dict:
    """The seed's own phase (and the gate after it) between a start and an outcome."""
    nodes = [{"id": "start", "type": "start"}, _seed_node(key, phase_id)]
    edges = [{"id": "1", "source_node_id": "start", "target_node_id": phase_id}]
    after = phase_id
    if gate_id:
        nodes.append(_seed_node(key, gate_id))
        edges.append({"id": "2", "source_node_id": phase_id, "target_node_id": gate_id})
        edges.append({"id": "3", "source_node_id": gate_id, "target_node_id": "done", "when": "passed"})
        edges.append({"id": "4", "source_node_id": gate_id, "target_node_id": "stopped", "when": "failed"})
        nodes.append({"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}})
    else:
        edges.append({"id": "2", "source_node_id": after, "target_node_id": "done"})
    nodes.append({"id": "done", "type": "outcome", "config": {"outcome": "done"}})
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


async def _device_session(db, user: User, workspace_id: str, *, run_id: str = "", root: str = ROOT
                          ) -> tuple[Session, str]:
    """A device job's gateway session: bound to the run its job carries, the job folder as repository root."""
    key = str(uuid.uuid4())
    identity = GatewayIdentity(user=user, grant_id="device-grant", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=key, work_item_key="", workflow_run_id=run_id)
    gateway = await get_or_create_gateway_session(db, identity)
    gateway.metadata_ = {**gateway.metadata_, "repository_binding": {"root": root}}
    await db.flush()
    return gateway, key


async def _run_with_session(db, definition: dict, *, item: bool = False) -> tuple[WorkflowRun, Session, str, str]:
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    work_item = None
    if item:
        work_item = WorkItem(source_type="jira", source_instance="t", source_key="BRD-7", title="Wrap text",
                             project_id=workspace_id)
        db.add(work_item)
        await db.flush()
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=workspace_id,
                          session=await new_chat_session(db, admin, workspace_id))
    if work_item is not None:
        run.work_item_id = work_item.id
    gateway, key = await _device_session(db, admin, workspace_id, run_id=run.id)
    return run, gateway, key, workspace_id


def _caller(user: User, workspace_id: str, key: str | None) -> McpCaller:
    return McpCaller(user_id=user.id, grant_id="device-grant", scopes=DEVICE_SCOPES, workspace_header=workspace_id,
                     session_key=key)


async def _native(db, gateway: Session, tool: str, tool_input: dict, *, cwd: str = ROOT, hook: str | None = "PostToolUse",
                  transcript: bool = True) -> list[ToolCall]:
    """One native tool call as the server records it: the PostToolUse hook and/or the proxied transcript."""
    tool_use_id = f"toolu_{uuid.uuid4().hex[:12]}"
    if hook:
        await record_tool_execution(db, session=gateway, hook_input={
            "hook_event_name": hook, "tool_name": tool, "tool_use_id": tool_use_id, "cwd": cwd,
            "tool_input": tool_input, "tool_response": {"content": "..."}})
    if transcript:
        messages = [{"role": "user", "content": "go"},
                    {"role": "assistant", "content": [{"type": "tool_use", "id": tool_use_id, "name": tool,
                                                       "input": tool_input}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                                  "content": "file content", "is_error": hook == "PostToolUseFailure"}]}]
        await upsert_gateway_tool_calls(db, gateway.id, newest_turn(messages))
    await db.flush()
    return [row for row in await _rows(db, gateway) if row.request_id == tool_use_id]


async def _rows(db, gateway: Session) -> list[ToolCall]:
    from sqlalchemy import select

    return list((await db.execute(select(ToolCall).where(ToolCall.session_id == gateway.id))).scalars())


def _mcp_row(gateway: Session, tool: str, *, excerpt: str = "{}", ok: bool = True) -> ToolCall:
    return ToolCall(session_id=gateway.id, tool_name=PREFIX + tool, request_id=f"toolu_{uuid.uuid4().hex[:12]}",
                    parameters={"source": "model_gateway", "block_index": 0},
                    result={"is_error": not ok, "excerpt": excerpt}, status="success",
                    created_at=utc_now() + timedelta(seconds=1))


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
