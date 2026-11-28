"""Deleting a connector releases the stored secrets only it referenced (F1, lifecycle secret hygiene)."""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import Base
from app.models import (
    AuditLog,
    BuiltInToolConfig,
    LLMProvider,
    Project,
    SecretAccessAuditLog,
    SecretRotationLog,
    StoredSecret,
)
from app.services.admin.connector import admin_connector_service
from app.services.secret import set_secret_value
from app.web._helpers.panel_serializers import _serialize_connector

_TOKEN_VALUE = "jira-token-value-never-printed"
_PASSWORD_VALUE = "jira-password-value-never-printed"


async def _save_jira(db: AsyncSession, owner_id: str | None) -> BuiltInToolConfig:
    await admin_connector_service.save_connector(
        db,
        tool_name="jira",
        payload={
            "jira_auth_mode": "cloud_api_token",
            "is_active": True,
            "jira_url": "https://jira.example.com",
            "jira_email": "agent@example.com",
            "jira_token": _TOKEN_VALUE,
            "jira_password": _PASSWORD_VALUE,
        },
        serialize_connector=_serialize_connector,
        owner_id=owner_id,
    )
    return (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.tool_name == "jira", BuiltInToolConfig.project_id.is_(None)
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_delete_connector_deletes_its_own_secret_and_keeps_one_another_config_references(db, auth_user):
    entry = await _save_jira(db, auth_user.id)
    token_id = entry.config["jira_token_secret_ref"]
    password_id = entry.config["jira_password_secret_ref"]
    db.add(SecretRotationLog(id=str(uuid.uuid4()), secret_id=token_id, action="rotated"))
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    db.add(
        BuiltInToolConfig(
            tool_name="jira",
            project_id=project.id,
            config={"jira_url": "https://jira.example.com", "jira_password_secret_ref": f"secret:{password_id}"},
            is_active=True,
        )
    )
    await db.flush()

    result = await admin_connector_service.delete_connector(db, tool_name="jira", actor_user_id=auth_user.id)

    assert result["status"] == "deleted"
    assert await db.get(StoredSecret, token_id) is None
    assert (await db.execute(select(SecretRotationLog).where(SecretRotationLog.secret_id == token_id))).first() is None
    assert await db.get(StoredSecret, password_id) is not None
    entries = result["stored_entries"]
    assert [item["id"] for item in entries["deleted"]] == [token_id]
    assert entries["deleted"][0]["name"] == "jira_jira_token"
    assert entries["kept"] == [
        {
            "id": password_id,
            "name": "jira_jira_password",
            "field_name": "jira_password",
            "state": "kept_still_referenced",
            "held_by": ["built_in_tool_configs"],
        }
    ]
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "admin.connector.deleted"))
    ).scalar_one()
    assert audit.details["stored_entries"] == entries
    serialized = json.dumps([result, audit.details])
    assert _TOKEN_VALUE not in serialized
    assert _PASSWORD_VALUE not in serialized


def _foreign_keys_on(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.mark.asyncio
async def test_delete_connector_release_respects_foreign_keys(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    sa.event.listen(engine.sync_engine, "connect", _foreign_keys_on)
    try:
        async with engine.begin() as conn:
            assert (await conn.execute(sa.text("PRAGMA foreign_keys"))).scalar() == 1
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            entry = await _save_jira(db, None)
            token_id = entry.config["jira_token_secret_ref"]
            password_id = entry.config["jira_password_secret_ref"]
            db.add(SecretRotationLog(id=str(uuid.uuid4()), secret_id=token_id, action="rotated"))
            db.add(SecretAccessAuditLog(secret_id=token_id, action="read", outcome="success"))
            # A column holder outside any connector config keeps its secret.
            db.add(LLMProvider(name="fk-provider", api_key_secret_ref=password_id))
            await db.commit()

            result = await admin_connector_service.delete_connector(db, tool_name="jira", actor_user_id=None)

            assert [item["id"] for item in result["stored_entries"]["deleted"]] == [token_id]
            assert result["stored_entries"]["kept"][0]["held_by"] == ["llm_providers"]
            assert await db.get(StoredSecret, token_id) is None
            detached = (await db.execute(select(SecretAccessAuditLog))).scalars().all()
            assert [row.secret_id for row in detached] == [None]
            resaved = await set_secret_value(db, tool_name="jira", field_name="jira_token", project_id=None,
                                               value="next")
            assert resaved.id != token_id
    finally:
        await engine.dispose()
