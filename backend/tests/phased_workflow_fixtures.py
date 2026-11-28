"""A small phased workflow for the workflow run tests: one phase, a gate, a bounded loop back, an outcome."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import select

from app.models import User
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version

PHASE = {
    "agent": "engineer",
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
    from app.models.security.user import UserProject

    if await db.get(UserProject, (user.id, project_id)) is None:
        db.add(UserProject(user_id=user.id, project_id=project_id, role=role))
        await db.flush()


async def requester_workspace(db, user: User) -> str:
    from app.models import Project

    project = Project(id=str(uuid.uuid4()), name=f"runs-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    await join_workspace(db, user, project.id)
    return project.id


async def run_workspace(db, user: User, work_item_id: str | None = None) -> str:
    from app.models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, work_item_id) if work_item_id else None
    if item is not None and item.project_id:
        await join_workspace(db, user, item.project_id)
        return item.project_id
    workspace_id = await requester_workspace(db, user)
    if item is not None:
        item.project_id = workspace_id
        await db.flush()
    return workspace_id


async def member_admin(db, project_id: str) -> User:
    admin = await admin_user(db)
    await join_workspace(db, admin, project_id)
    return admin


REVIEWER_USERNAME = "phased-reviewer"


async def reviewer_user(db) -> User:
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
    from tests.phase_turn_support import finish_phase_turn

    return await finish_phase_turn(db, session_id, resolution,
                                   [{"tool_name": name, "status": "success", "result": {}} for name in tools])
