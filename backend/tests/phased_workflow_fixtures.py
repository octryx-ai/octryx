"""A small phased workflow for the workflow run tests: one phase, a gate, a bounded loop back, an outcome."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import select

from app.agent.loops.response._loop_workflow_checks import handle_workflow_checks_guard
from app.models import User
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

PHASE = {
    "agent": "engineer",  # every phase names its platform agent
    "workflow_id": "knowledge_request",
    "workflow_class": "knowledge_request",
    "workflow_contract": {
        "workflow_id": "knowledge_request", "workflow_class": "knowledge_request", "capability_class": "read_only",
        "when_to_use": "Collect the evidence for the item.",
        "checks": [{"type": "tool_called", "params": {"tools": ["knowledge_search"]}, "blocking": True,
                    "description": "Evidence searched"}],
    },
    "tool_policy": {"allowlist": ["knowledge_search", "knowledge_read"], "denylist": []},
}


def phased_definition(*, max_iterations: int = 1, extra_nodes: list[dict] | None = None,
                      edges: list[dict] | None = None) -> dict[str, Any]:
    nodes = [
        {"id": "start", "type": "start", "label": "Start"},
        {"id": "work", "type": "phase", "label": "Collect evidence", "config": copy.deepcopy(PHASE)},
        {"id": "verify", "type": "gate", "label": "Evidence read",
         "config": {"checks": [{"type": "tool_called", "params": {"tools": ["knowledge_read"]}, "blocking": True,
                                "description": "A source was read"}]}},
        {"id": "done", "type": "outcome", "label": "Done", "config": {"outcome": "done"}},
        *(extra_nodes or []),
    ]
    return {
        "execution_kind": "phased",
        "nodes": nodes,
        "edges": edges if edges is not None else [
            {"id": "e1", "source_node_id": "start", "target_node_id": "work"},
            {"id": "e2", "source_node_id": "work", "target_node_id": "verify"},
            {"id": "e3", "source_node_id": "verify", "target_node_id": "done", "when": "passed"},
            {"id": "rework", "source_node_id": "verify", "target_node_id": "work", "when": "failed", "kind": "loop",
             "max_iterations": max_iterations, "label": "Rework"},
        ],
    }


async def admin_user(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def join_workspace(db, user: User, project_id: str, *, role: str = "admin") -> None:
    """``user`` becomes a member of the Workspace, the way a real requester is: a platform admin outside the run's
    Workspace is no default decider (``workflow_runs.responsible.responsible_decider``)."""
    from app.models.security.user import UserProject

    if await db.get(UserProject, (user.id, project_id)) is None:
        db.add(UserProject(user_id=user.id, project_id=project_id, role=role))
        await db.flush()


async def requester_workspace(db, user: User) -> str:
    """A fresh active Workspace with ``user`` as a member; the id."""
    from app.models import Project

    project = Project(id=str(uuid.uuid4()), name=f"runs-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    await join_workspace(db, user, project.id)
    return project.id


async def run_workspace(db, user: User, work_item_id: str | None = None) -> str:
    """The Workspace a test run starts in, with ``user`` as a member: the Work item's, else a fresh one (which a
    Work item without a Workspace then belongs to)."""
    from app.models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, work_item_id) if work_item_id else None
    if item is not None and item.project_id:
        await join_workspace(db, user, item.project_id)
        return item.project_id
    workspace_id = await requester_workspace(db, user)
    if item is not None:  # a Work item belongs to the Workspace its run works in
        item.project_id = workspace_id
        await db.flush()
    return workspace_id


async def member_admin(db, project_id: str) -> User:
    """The platform admin as a member of ``project_id`` (the requester of a run in it)."""
    admin = await admin_user(db)
    await join_workspace(db, admin, project_id)
    return admin


REVIEWER_USERNAME = "phased-reviewer"


async def reviewer_user(db) -> User:
    """A second admin: a phased version is published by an admin other than its author (D2b2 four-eyes)."""
    from app.models import Role, UserRole

    user = (await db.execute(select(User).where(User.username == REVIEWER_USERNAME))).scalar_one_or_none()
    if user is not None:
        return user
    user = User(id=str(uuid.uuid4()), username=REVIEWER_USERNAME, email=f"{REVIEWER_USERNAME}@example.com",
                password_hash="x", is_active=True)
    db.add(user)
    await db.flush()
    role_id = (await db.execute(select(Role.id).where(Role.name == "admin"))).scalar_one_or_none()
    if role_id is not None:
        db.add(UserRole(user_id=user.id, role_id=role_id))
        await db.flush()
    return user


async def publish_phased(db, definition: dict[str, Any], *, key: str | None = None) -> str:
    admin = await admin_user(db)
    key = key or f"phased-{uuid.uuid4().hex[:8]}"
    created = await create_flow_definition(db, current_user=admin, payload={
        "key": key, "name": "Evidence run", "definition": definition,
    })
    version_id = created["versions"][0]["id"]
    # The admin authors, a second admin publishes (four-eyes for every phased version).
    await publish_flow_definition_version(db, version_id=version_id, current_user=await reviewer_user(db))
    return key


async def phase_turn(db, session_id: str, resolution: dict, tools: list[str]) -> Any:
    """One governed chat turn's end: the real turn-end checks guard with the given successful tool calls."""
    history = [{"tool_name": name, "status": "success", "result": {}} for name in tools]

    async def persist_turn_trace(**_kwargs):
        return None

    with prompt_set_scope(seed_prompt_set()):
        return await handle_workflow_checks_guard(
            db=db, session_id=session_id, runtime={"provider_name": "test"}, response={"usage": {}},
            request_messages=[], messages=[], context_snapshot={}, runtime_attempts=[], runtime_settings={},
            usage_model="m", content="Done.", tool_calls=None, has_followup_steps=False, sub_agent_depth=0,
            request_analysis={ROUTING_RESOLUTION_KEY: resolution}, turn_tool_history=history,
            persist_turn_trace=persist_turn_trace,
        )
