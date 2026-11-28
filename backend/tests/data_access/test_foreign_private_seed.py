from __future__ import annotations

from app.db.workspace_bound import workspace_bound_models
from app.services.project.private_workspace import ensure_private_workspace
from tests.data_access.foreign_private_rows import seed_foreign_private_rows
from tests.devices.device_support import user_named


async def test_every_workspace_bound_model_gets_one_row_in_a_foreign_private_workspace(db):
    owner = await user_named(db, "pg5-walker-owner")
    workspace = await ensure_private_workspace(db, owner)
    seeded = await seed_foreign_private_rows(db, workspace.id, owner.id)
    assert set(seeded.rows) == {model.__table__.name for model in workspace_bound_models()}
