"""Sessions by the person's role in the Workspace: viewer reads, member edits, only an owner may use
bypass; the Workspace's own switches tighten further."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.security.user import UserProject
from app.services.agent_gateway.role_modes import (
    allowed_modes,
    role_ceiling,
    session_ceiling,
    workspace_ceiling,
)
from tests.devices.device_support import user_named


def test_role_ceilings_and_modes():
    assert [role_ceiling(r) for r in ("owner", "member", "admin", "viewer", None, "editor")] == [
        "bypass", "edit", "bypass", "read_only", "read_only", "edit"]
    assert allowed_modes("read_only") == ["plan"]
    assert "bypassPermissions" not in allowed_modes("edit")
    assert allowed_modes("bypass")[-1] == "bypassPermissions"
    assert workspace_ceiling(Project(name="x", config={"agent_gateway_policy": {"free_sessions": "read_only"}})) \
        == "read_only"
    assert workspace_ceiling(Project(name="x", config={"agent_gateway_policy": {"bypass_permissions": "disabled"}})) \
        == "edit"


@pytest.mark.asyncio
async def test_session_ceiling_by_membership_and_workspace(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    viewer, member, owner = [await user_named(db, n) for n in ("v1", "m1", "o1")]
    db.add_all([UserProject(user_id=viewer.id, project_id=project.id, role="viewer"),
                UserProject(user_id=member.id, project_id=project.id, role="member"),
                UserProject(user_id=owner.id, project_id=project.id, role="owner")])
    await db.flush()
    assert await session_ceiling(db, user_id=viewer.id, workspace_id=project.id) == "read_only"
    assert await session_ceiling(db, user_id=member.id, workspace_id=project.id) == "edit"
    assert await session_ceiling(db, user_id=owner.id, workspace_id=project.id) == "bypass"
    stranger = await user_named(db, "s1")
    assert await session_ceiling(db, user_id=stranger.id, workspace_id=project.id) == "read_only"
    project.config = {**(project.config or {}), "agent_gateway_policy": {"bypass_permissions": "disabled"}}
    await db.flush()
    assert await session_ceiling(db, user_id=owner.id, workspace_id=project.id) == "edit"
    # The Workspace's admins set each role's ceiling.
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        "role_modes": {"member": "read_only", "viewer": "edit", "owner": "edit"}}}
    await db.flush()
    assert await session_ceiling(db, user_id=member.id, workspace_id=project.id) == "read_only"
    assert await session_ceiling(db, user_id=viewer.id, workspace_id=project.id) == "edit"
    assert await session_ceiling(db, user_id=owner.id, workspace_id=project.id) == "edit"


def test_role_modes_policy_is_validated():
    from app.services.agent_gateway.policy_keys import AgentGatewayPolicyError
    from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy

    assert normalize_agent_gateway_policy({"role_modes": {"admin": "edit"}})["role_modes"] == {"admin": "edit"}
    for bad in ({"root": "bypass"}, {"member": "god"}, ["member"]):
        with pytest.raises(AgentGatewayPolicyError):
            normalize_agent_gateway_policy({"role_modes": bad})


def test_a_workspace_admin_may_lower_but_not_raise_a_role():
    from app.services.workspace_settings.bounds import LooseningRefusedError, check_role_modes

    current = {"viewer": "read_only", "member": "edit", "owner": "bypass", "admin": "bypass"}
    check_role_modes(current, {"member": "read_only", "owner": "edit"})
    with pytest.raises(LooseningRefusedError):
        check_role_modes(current, {"member": "bypass"})
