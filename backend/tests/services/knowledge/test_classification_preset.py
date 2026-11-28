from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.knowledge.projection.workspace_classification_values import (
    DEFAULT_SET,
    DEFAULT_UNSET,
    PRESET_CLASSIFICATION,
    instance_default_classification,
)


@pytest.mark.parametrize(("configured", "expected"), [
    ("", (PRESET_CLASSIFICATION, DEFAULT_SET)),
    ("confidential", ("confidential", DEFAULT_SET)),
    ("none", (None, DEFAULT_UNSET)),
    (" NONE ", (None, DEFAULT_UNSET)),
])
def test_the_preset_is_internal_and_none_keeps_workspaces_unclassified(monkeypatch, configured, expected):
    monkeypatch.setattr(get_settings(), "knowledge_default_data_classification", configured)
    assert instance_default_classification() == expected


@pytest.mark.asyncio
async def test_a_private_workspace_of_a_fresh_installation_is_classified_internal(db, monkeypatch):
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import user_named

    monkeypatch.setattr(get_settings(), "knowledge_default_data_classification", "")
    project = await ensure_private_workspace(db, await user_named(db, "fresh-person"))
    assert dict(dict(project.config or {}).get("data_policy") or {}).get("classification") == PRESET_CLASSIFICATION



@pytest.mark.asyncio
async def test_a_new_workspace_carries_the_default_in_its_creation_insert(db, monkeypatch):
    # A separate write after the creation is what SQLite refused under parallel bootstraps (batch 52).
    from sqlalchemy import event

    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import user_named

    writes: list[str] = []

    def seen(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(("INSERT INTO projects", "UPDATE projects")):
            writes.append(f"{statement.split()[0]} {parameters}")

    monkeypatch.setattr(get_settings(), "knowledge_default_data_classification", "")
    user = await user_named(db, "busy-person")
    engine = (await db.connection()).sync_engine
    event.listen(engine, "before_cursor_execute", seen)
    try:
        await ensure_private_workspace(db, user)
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    assert writes[0].startswith("INSERT") and f'"classification": "{PRESET_CLASSIFICATION}"' in writes[0]
