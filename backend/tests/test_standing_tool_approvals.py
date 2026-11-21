""""Always for this Workspace" for tool approvals, on the same governed approval record.

- A pending tool approval names the scope "Always" would grant (Workspace + tool, plus the
  exec-policy argument class for command tools); the chat sees it as ``standingRule``.
- Only a Workspace admin or owner may grant (403 otherwise, nothing decided); the chat state
  tells the client (``canGrantStandingConfirmation``) so the button is hidden for everyone else.
- A granted rule answers the next call of exactly that scope; another argument class still asks.
- An admin revokes the rule in the Workspace config; every write is audited.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Approval, AuditLog, ChangePreview, Project, User, UserProject
from app.models import Session as ChatSession
from app.services.auth import create_access_token
from app.services.change_preview import serialize_change_preview
from app.services.security_analyzer.contract import SecurityAnalyzerFinding
from app.services.standing_approvals.argument_class import (
    command_argument_class,
    command_review_scope,
    standing_rule_scope,
)
from app.services.standing_approvals.decision import decide_approval_always
from app.services.tool_approval_gate import enforce_tool_approval
from app.tools.context import ToolContext
from app.web._helpers.approval_serialization import _serialize_approval

POLICY = {"approval_policy": {"require_for_tools": ["run_cli_command"]}}


async def _user(db, role: str, project: Project) -> User:
    user = User(
        id=str(uuid.uuid4()), username=f"{role}-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@t.local",
        password_hash="x", auth_source="local",
    )
    db.add(user)
    await db.flush()
    db.add(UserProject(user_id=user.id, project_id=project.id, role=role, granted_by=user.id))
    await db.flush()
    return user


async def _workspace(db):
    project = Project(id=str(uuid.uuid4()), name=f"w28-{uuid.uuid4().hex[:8]}", config=dict(POLICY), is_active=True)
    db.add(project)
    await db.flush()
    owner = await _user(db, "owner", project)
    member = await _user(db, "member", project)
    return project, owner, member


async def _session(db, project: Project, user: User) -> ChatSession:
    session = ChatSession(user_id=user.id, project_id=project.id, metadata_={})
    db.add(session)
    await db.flush()
    return session


def _context(db, session: ChatSession, project: Project) -> ToolContext:
    return ToolContext(
        user_id=session.user_id, project_ids=[project.id], roles=[], session_id=session.id,
        project_config=dict(POLICY), db=db,
    )


async def _call(db, session, project, command: str):
    return await enforce_tool_approval("run_cli_command", {"command": command}, _context(db, session, project))


def test_the_scope_follows_the_exec_policy_classes_and_refuses_compound_commands():
    assert command_argument_class("run_cli_command", "git status --short") == "git status"
    assert command_argument_class("run_cli_command", "npm test") == "npm"
    assert command_argument_class("run_kubectl", ["/opt/bin/kubectl", "-n", "prod", "get", "pods"]) == "kubectl get"
    for compound in ("ls && rm -rf x", "cat a > b", "echo $(id)", "/bin/rm x", "git --version"):
        assert command_argument_class("run_cli_command", compound) is None, compound
    assert standing_rule_scope("run_kubectl", {"args": ["delete", "pod", "x"]}).argument_class == "kubectl delete"
    assert standing_rule_scope("write_file", {"path": "x"}).to_payload() == {
        "tool_name": "write_file", "argument_class": None,
    }
    policy = SecurityAnalyzerFinding("exec_policy", "review", "medium", "r", {})
    secret = SecurityAnalyzerFinding("secret_access", "review", "high", "r", {})
    assert command_review_scope("run_cli_command", "git push", [policy]).argument_class == "git push"
    # A content analyzer's review judges this exact command: it keeps asking.
    assert command_review_scope("run_cli_command", "git push", [policy, secret]) is None


@pytest.mark.asyncio
async def test_always_is_admin_only_answers_the_next_call_and_is_revocable_with_audit(client, db):
    project, owner, member = await _workspace(db)

    # A member's own pending approval: the scope is offered, but the member may not grant it.
    member_session = await _session(db, project, member)
    blocked = await _call(db, member_session, project, "git status")
    assert blocked["approval_required"] is True
    preview = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == blocked["approval_id"])))
    view = _serialize_approval(
        await db.get(Approval, blocked["approval_id"]), change_preview=serialize_change_preview(preview.scalar_one())
    )
    assert view["standingRule"] == {"toolName": "run_cli_command", "argumentClass": "git status"}
    with pytest.raises(HTTPException) as refused:
        await decide_approval_always(db, approval_id=blocked["approval_id"], decider_id=member.id)
    assert refused.value.status_code == 403
    assert (await db.get(Approval, blocked["approval_id"])).status == "pending"

    member_state = await client.get(
        f"/chat/api/bootstrap?session_id={member_session.id}",
        headers={"Authorization": f"Bearer {create_access_token(member.id)}"},
    )
    assert member_state.status_code == 200, member_state.text
    assert member_state.json()["selectedSession"]["canGrantStandingConfirmation"] is False

    # The Workspace owner grants "Always" on the owner's approval: rule recorded, approval approved.
    owner_session = await _session(db, project, owner)
    owner_state = await client.get(
        f"/chat/api/bootstrap?session_id={owner_session.id}",
        headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
    )
    assert owner_state.json()["selectedSession"]["canGrantStandingConfirmation"] is True
    pending = await _call(db, owner_session, project, "git status")
    decided = await decide_approval_always(db, approval_id=pending["approval_id"], decider_id=owner.id)
    assert decided.status == "approved"
    await db.refresh(project)
    [rule] = project.config["standing_tool_approvals"]["rules"]
    assert (rule["tool_name"], rule["argument_class"], rule["granted_by"]) == ("run_cli_command", "git status", owner.id)

    # The next call of exactly that scope runs without asking, in any session of the Workspace.
    approvals_before = len((await db.execute(select(Approval))).scalars().all())
    assert await _call(db, member_session, project, "git status -s") is None
    assert len((await db.execute(select(Approval))).scalars().all()) == approvals_before
    # Another argument class still asks.
    assert (await _call(db, member_session, project, "git push"))["approval_required"] is True

    # An admin revokes it in the Workspace config: the next call asks again.
    revoke = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/config",
        json={"standing_tool_approvals": {"rules": []}},
        headers={"Authorization": f"Bearer {create_access_token((await _admin(db)).id)}"},
    )
    assert revoke.status_code == 200, revoke.text
    await db.refresh(project)
    assert (await _call(db, member_session, project, "git status"))["approval_required"] is True

    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.resource_type == "project_config", AuditLog.resource_id == project.id)
        )
    ).scalars().all()
    assert len(audit) == 2, "the grant and the revoke are both audited project-config writes"

    # A stored value outside the vocabulary is refused with a closed code.
    invalid = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/config",
        json={"standing_tool_approvals": {"rules": [{"tool_name": "run_cli_command", "argument_class": "a b c"}]}},
        headers={"Authorization": f"Bearer {create_access_token((await _admin(db)).id)}"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["errors"][0]["code"] == "invalid_argument_class"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
