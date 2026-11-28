"""Shared helpers for the test_workflow_run_octryx_* modules."""

from __future__ import annotations

import copy
import uuid

import pytest

from app.models import Session, ToolCall, User, WorkflowRun
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.policy import load_workspace_policy
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.agent_gateway.tool_decision import decide_tool_check
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased

ROOT = "/work/repo"


CONFIRMED = "tests/test_totals.py"


def _fix_definition(*, capability: str = "change", tools: list[str] | None = None, protect: bool = True) -> dict:
    fix = copy.deepcopy(PHASE)
    fix["workflow_contract"].update(capability_class=capability, checks=[
        {"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "blocking": True,
         "description": "The test suite ran"},
        {"type": "test_command_passed", "params": {}, "blocking": True,
         "description": "The tests ran green after the change"}])
    if protect:
        fix["workflow_contract"]["path_rules"] = {"protect_confirmed_tests": True}
    fix["tool_policy"]["allowlist"] = tools or ["read_workspace_file", "edit_workspace_file", "run_test_suite"]
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "fix", "type": "phase", "label": "Minimal fix", "config": fix},
                  {"id": "green", "type": "gate", "config": {"phase": "fix", "checks": [
                      {"type": "tests_green", "params": {}, "blocking": True, "description": "Green"}]}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "fix"},
                  {"id": "2", "source_node_id": "fix", "target_node_id": "green"},
                  {"id": "3", "source_node_id": "green", "target_node_id": "done", "when": "passed"},
                  {"id": "loop", "source_node_id": "green", "target_node_id": "fix", "when": "failed",
                   "kind": "loop", "max_iterations": 1, "label": "Fix ↔ test"}],
    }


async def _launcher(db, user: User, workspace_id: str, *, run_id: str = "", root: str = ROOT) -> tuple[Session, str]:
    key = str(uuid.uuid4())
    identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=key, work_item_key="", workflow_run_id=run_id)
    gateway = await get_or_create_gateway_session(db, identity)
    gateway.metadata_ = {**gateway.metadata_, "repository_binding": {"root": root}}
    await db.flush()
    return gateway, key


async def _bound_run(db, definition: dict | None = None) -> tuple[WorkflowRun, Session, str, str]:
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or _fix_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    gateway, key = await _launcher(db, admin, workspace_id, run_id=run.id)
    return run, gateway, key, workspace_id


async def set_tool_defaults(db, workspace_id: str, **values) -> None:
    from app.models import Project

    project = await db.get(Project, workspace_id)
    config = dict(project.config or {})
    gateway = dict(config.get("agent_gateway_policy") or {})
    gateway["device_runs"] = {**dict(gateway.get("device_runs") or {}), "tool_defaults": dict(values)}
    project.config = {**config, "agent_gateway_policy": gateway}
    await db.flush()


STRICT = {"unknown_tools": "deny", "web_tools": "research_only", "shell": "strict", "path_rules": "strict",
          "device_models": "list_only", "network": "allowlist", "browser": "loopback"}


def _hook(tool: str, **tool_input) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": ROOT, "tool_input": tool_input}


async def _decide(db, gateway, key, workspace_id, hook) -> dict:
    policy = (await load_workspace_policy(db, workspace_id)).policy
    return await decide_tool_check(db, session=gateway, session_key=key, policy=policy, hook_input=hook)


def _call(gateway: Session, tool: str, *, at, ok: bool = True, **parameters) -> ToolCall:
    return ToolCall(session_id=gateway.id, tool_name=tool, parameters={"source": "gateway", **parameters},
                    result={"is_error": not ok, "excerpt": parameters.pop("excerpt", "")}, status="success",
                    created_at=at)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
