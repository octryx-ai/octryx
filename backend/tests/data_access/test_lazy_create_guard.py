from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import WorkspaceCapabilityBinding
from app.services.data_access import as_viewer
from app.services.data_access.read_filter import HiddenWorkspaceError
from app.services.project.private_workspace import ensure_private_workspace
from app.services.workspace_models.store import read_models
from tests.devices.device_support import user_named
from tests.phased_workflow_fixtures import admin_user


async def _bindings(db, workspace_id: str) -> list[tuple]:
    rows = await db.execute(select(WorkspaceCapabilityBinding.id, WorkspaceCapabilityBinding.updated_at).where(
        WorkspaceCapabilityBinding.workspace_id == workspace_id))
    return sorted(rows.all())


async def test_a_lazy_create_in_a_hidden_workspace_fails_clearly_and_leaves_its_rows_alone(db):
    owner = await user_named(db, "lazy-create-owner")
    private = await ensure_private_workspace(db, owner)
    admin = await admin_user(db)
    await db.commit()
    with as_viewer(owner.id):
        await read_models(db, private.id)  # the owner's first visit creates the Workspace's bindings
    before = await _bindings(db, private.id)
    assert before

    with as_viewer(admin.id), pytest.raises(HiddenWorkspaceError, match=private.id):
        await read_models(db, private.id)

    assert await _bindings(db, private.id) == before
    count = select(func.count()).select_from(WorkspaceCapabilityBinding)
    with as_viewer(admin.id):
        assert (await db.execute(count.where(WorkspaceCapabilityBinding.workspace_id == private.id))).scalar() == 0
