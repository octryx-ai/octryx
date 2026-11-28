"""Workflow and Workspace texts of the prompt catalog: written by those with rights at that scope, approved
by another such person, audited per step; agent texts stay refused."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, AuditLog, Project, User, UserProject
from app.models.runtime.flow_definition import FlowDefinition
from app.services.prompt_catalog import lifecycle

KEY = "run.read_contract"


async def _user(db) -> User:
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", email=f"u-{uuid.uuid4().hex[:8]}@x.test", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _workspace(db, *members: tuple[User, str]) -> Project:
    project = Project(name=f"scope-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    for user, role in members:
        db.add(UserProject(user_id=user.id, project_id=project.id, role=role))
    await db.flush()
    return project


async def _draft(db, user, scope_type, scope_id, body="Mine {run_id}."):
    return await lifecycle.create_draft(db, key=KEY, scope_type=scope_type, scope_id=scope_id, body=body,
                                        change_note="test", user=user)


async def _approve(db, version, approver):
    approval = await db.get(Approval, version.approval_id)
    approval.status, approval.approved_by = "approved", approver.id
    await db.flush()
    return approval


@pytest.mark.asyncio
async def test_a_workspace_owner_writes_its_texts_and_another_owner_approves(db):
    owner, second, member, stranger = await _user(db), await _user(db), await _user(db), await _user(db)
    workspace = await _workspace(db, (owner, "owner"), (second, "admin"), (member, "member"))
    for user in (member, stranger):
        with pytest.raises(lifecycle.PromptCatalogRefusal) as refused:
            await _draft(db, user, "workspace", workspace.id)
        assert (refused.value.code, refused.value.status) == ("prompt_scope_forbidden", 403)
    _template, draft = await _draft(db, owner, "workspace", workspace.id)
    submitted = await lifecycle.submit_for_review(db, version_id=draft.id, user=owner)
    approval = await _approve(db, submitted, stranger)  # no rights at this scope
    with pytest.raises(lifecycle.PromptCatalogRefusal) as gate:
        await lifecycle.publish(db, version_id=draft.id, user=owner, approval_id=approval.id)
    assert gate.value.code == "governance_approval_required"
    approval.approved_by = owner.id  # the author: four eyes refuse it
    with pytest.raises(lifecycle.PromptCatalogRefusal):
        await lifecycle.publish(db, version_id=draft.id, user=owner, approval_id=approval.id)
    approval.approved_by = second.id
    published, _gate = await lifecycle.publish(db, version_id=draft.id, user=owner, approval_id=approval.id)
    assert published.state == "published"
    actions = (await db.execute(select(AuditLog.action).where(AuditLog.user_id == owner.id))).scalars().all()
    assert {"prompt_catalog.draft", "prompt_catalog.submit", "prompt_catalog.publish"} <= set(actions)


@pytest.mark.asyncio
async def test_a_workflows_owner_writes_its_texts_and_nobody_else(db):
    owner, other = await _user(db), await _user(db)
    db.add(FlowDefinition(key="my-flow", name="Mine", project_id=None, created_by=owner.id))
    await db.flush()
    _template, draft = await _draft(db, owner, "workflow", "my-flow")
    assert draft.state == "draft"
    with pytest.raises(lifecycle.PromptCatalogRefusal) as refused:
        await _draft(db, other, "workflow", "my-flow")
    assert refused.value.code == "prompt_scope_forbidden"
    with pytest.raises(lifecycle.PromptCatalogRefusal) as unknown:
        await _draft(db, owner, "workflow", "no-such-flow")
    assert (unknown.value.code, unknown.value.status) == ("prompt_workflow_not_found", 404)
    with pytest.raises(lifecycle.PromptCatalogRefusal) as foreign:
        await lifecycle.submit_for_review(db, version_id=draft.id, user=other)
    assert foreign.value.code == "prompt_scope_forbidden"


@pytest.mark.asyncio
async def test_the_workflow_owner_approves_another_authors_text_of_the_workflow(db):
    from fastapi import HTTPException

    from app.services.approval.access import approval_visibility_clause, decide_sessionless_approval
    from tests.prompt_catalog_publish_support import admin_user

    owner, stranger, admin = await _user(db), await _user(db), await admin_user(db)
    db.add(FlowDefinition(key="owned-flow", name="Owned", project_id=None, created_by=owner.id))
    await db.flush()
    _template, draft = await _draft(db, admin, "workflow", "owned-flow")
    submitted = await lifecycle.submit_for_review(db, version_id=draft.id, user=admin)
    approval = await db.get(Approval, submitted.approval_id)
    seen = (await db.execute(select(Approval.id).where(await approval_visibility_clause(db, owner.id)))).scalars()
    assert approval.id in set(seen)
    with pytest.raises(HTTPException):
        await decide_sessionless_approval(db, approval=approval, decider_id=stranger.id, decision="approved",
                                          reason=None)
    decided = await decide_sessionless_approval(db, approval=approval, decider_id=owner.id, decision="approved",
                                                reason=None)
    assert decided.status == "approved"
    published, _gate = await lifecycle.publish(db, version_id=draft.id, user=admin, approval_id=approval.id)
    assert published.state == "published"


@pytest.mark.asyncio
async def test_the_writable_scopes_carry_labels_for_the_editor(db):
    from app.services.prompt_catalog.scope_rights import writable_scopes

    owner, member = await _user(db), await _user(db)
    workspace = await _workspace(db, (owner, "owner"), (member, "member"))
    db.add(FlowDefinition(key="labelled-flow", name="Labelled flow", project_id=None, created_by=owner.id))
    await db.flush()
    scopes = await writable_scopes(db, owner.id)
    assert {"scope_type": "workspace", "scope_id": workspace.id, "label": workspace.name} in scopes
    assert {"scope_type": "workflow", "scope_id": "labelled-flow", "label": "Labelled flow"} in scopes
    assert not [scope for scope in scopes if scope["scope_type"] == "global"]
    assert await writable_scopes(db, member.id) == []
