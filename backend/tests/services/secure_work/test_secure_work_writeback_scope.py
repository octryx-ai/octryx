"""Write-back definitions stay in their Workspace."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import AuditLog, Project, User, UserProject, WorkItem, WorkItemStateEvent
from app.services.auth.tokens import hash_password
from app.services.secure_work.lifecycle_transitions import default_workflow_for_item
from app.services.secure_work.workflow_mapping import dry_run_work_item_transition, transition_work_item
from app.time_utils import utc_now
from tests.secure_work_writeback_scope_support import _definition, _item, connectors, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _user(world, *projects: str) -> User:  # noqa: F811
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f"scope-{suffix}", email=f"scope-{suffix}@example.test",
                password_hash=hash_password("scope-Access-Pw-123"), is_active=True)
    world.db.add(user)
    await world.db.flush()
    world.db.add_all([UserProject(user_id=user.id, project_id=project_id) for project_id in projects])
    await world.db.flush()
    return user


async def _side_effects(world, item: WorkItem) -> tuple:  # noqa: F811
    events = await world.db.scalar(select(func.count()).select_from(WorkItemStateEvent)
                                   .where(WorkItemStateEvent.work_item_id == item.id))
    applied = await world.db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.resource_id == item.id, AuditLog.action == "secure_work.transition_applied"))
    return events, applied, item.work_state, item.updated_at


def _code(exc: pytest.ExceptionInfo) -> str | None:
    detail = exc.value.detail
    return detail.get("code") if isinstance(detail, dict) else None


async def _apply(world, workflow, item, user, *, check_access: bool):  # noqa: F811
    return await transition_work_item(world.db, workflow_id=workflow.id, work_item_id=item.id, current_user=user,
                                      payload={"to_state": "development", "reason": "scope test"},
                                      bind_preview=False, check_access=check_access)


async def test_resolver_never_returns_another_workspaces_definition(world):  # noqa: F811
    item_a = await _item(world, world.a)
    await _definition(world, world.a, active=False, default=True)
    await _definition(world, world.b, default=True)
    assert await default_workflow_for_item(world.db, item_a) is None
    assert await default_workflow_for_item(world.db, await _item(world, None)) is None


async def test_resolver_prefers_the_workspace_over_global_independent_of_order(world):  # noqa: F811
    own = await _definition(world, world.a, updated_at=utc_now() - timedelta(days=30))
    await _definition(world, None, default=True)
    assert await default_workflow_for_item(world.db, await _item(world, world.a)) == own


async def test_resolver_falls_back_to_global_for_every_item(world):  # noqa: F811
    global_row = await _definition(world, None)
    await _definition(world, world.b, active=False)
    for project_id in (world.a, None):
        assert await default_workflow_for_item(world.db, await _item(world, project_id)) == global_row


async def test_resolver_if_the_test_definition_were_active(world):  # noqa: F811
    db = world.db
    test_ws, acme_orders, sales = Project(name="Test ws"), Project(name="Acme Orders ws"), Project(name="Sales ws")
    db.add_all([test_ws, acme_orders, sales])
    await db.flush()
    test_definition = await _definition(world, test_ws.id)
    for project_id in (acme_orders.id, sales.id, None):
        assert await default_workflow_for_item(db, await _item(world, project_id)) is None
    assert await default_workflow_for_item(db, await _item(world, test_ws.id)) == test_definition


async def test_an_internal_apply_with_a_foreign_definition_is_refused_without_side_effects(world, connectors):  # noqa: F811
    item = await _item(world, world.a)
    foreign = await _definition(world, world.b)
    before = await _side_effects(world, item)
    with pytest.raises(HTTPException) as refused:
        await _apply(world, foreign, item, world.admin, check_access=False)
    assert (refused.value.status_code, _code(refused)) == (409, "workflow_project_mismatch")
    assert connectors == []
    assert await _side_effects(world, item) == before

    with pytest.raises(HTTPException) as dry:
        await dry_run_work_item_transition(world.db, workflow_id=foreign.id, work_item_id=item.id,
                                           current_user=world.admin, payload={"to_state": "development"})
    assert (dry.value.status_code, _code(dry)) == (409, "workflow_project_mismatch")
    assert connectors == []


async def test_the_scope_runs_before_the_active_check(world, connectors):  # noqa: F811
    item = await _item(world, world.a)
    inactive_foreign = await _definition(world, world.b, active=False)
    with pytest.raises(HTTPException) as refused:
        await _apply(world, inactive_foreign, item, world.admin, check_access=False)
    assert _code(refused) == "workflow_project_mismatch"
    assert connectors == []


async def test_an_internal_apply_with_the_own_or_a_global_definition_applies(world, connectors):  # noqa: F811
    for project_id in (world.a, None):
        item = await _item(world, world.a)
        workflow = await _definition(world, project_id)
        connectors.clear()
        result = await _apply(world, workflow, item, world.admin, check_access=False)
        assert (result["work_state"], item.work_state) == ("development", "development")
        assert connectors.count("execute_tracker_state_sync") == 1
        assert (await _side_effects(world, item))[:2] == (1, 1)


async def test_a_global_definition_passes_for_an_item_without_a_workspace(world, connectors):  # noqa: F811
    item = await _item(world, None)
    result = await _apply(world, await _definition(world, None), item, world.admin, check_access=False)
    assert result["work_state"] == "development"


async def test_a_user_with_access_applies_a_global_definition(world, connectors):  # noqa: F811
    member = await _user(world, world.a)
    item = await _item(world, world.a)
    workflow = await _definition(world, None)
    dry = await dry_run_work_item_transition(world.db, workflow_id=workflow.id, work_item_id=item.id,
                                             current_user=member, payload={"to_state": "development"})
    result = await transition_work_item(world.db, workflow_id=workflow.id, work_item_id=item.id, current_user=member,
                                        payload={"to_state": "development",
                                                 "effects_hash": dry["preview"]["jira_sync_preview"]["effects_hash"]})
    assert result["work_state"] == "development"


async def test_the_user_acl_comes_before_the_scope(world, connectors):  # noqa: F811
    item = await _item(world, world.a)
    foreign = await _definition(world, world.b)
    own = await _definition(world, world.a)
    only_a, both, outsider = await _user(world, world.a), await _user(world, world.a, world.b), await _user(world)
    for user, workflow, status, code in (
        (only_a, foreign, 404, None),
        (both, foreign, 409, "workflow_project_mismatch"),
        (outsider, own, 404, None),
    ):
        for call in (
            lambda: _apply(world, workflow, item, user, check_access=True),
            lambda: dry_run_work_item_transition(world.db, workflow_id=workflow.id, work_item_id=item.id,
                                                 current_user=user, payload={"to_state": "development"}),
        ):
            with pytest.raises(HTTPException) as refused:
                await call()
            assert (refused.value.status_code, _code(refused)) == (status, code)
    assert connectors == []
    assert item.work_state == "intake"
