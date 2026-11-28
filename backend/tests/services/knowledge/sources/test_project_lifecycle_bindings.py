"""Lifecycle of what is bound to a project: soft delete (F2) and connector delete (F4)."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.routes.knowledge.knowledge_source_connectors import delete_workspace_connector
from app.db import Base
from app.models import AuditLog, BuiltInToolConfig, Project, User
from app.models.project.knowledge_source_sync import (
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
)
from app.services.execution_profile_service import build_execution_profile
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.removal import delete_connector
from app.services.knowledge.sources.sync.runner import SyncRefusedError
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.project_lifecycle_service import delete_project_for_admin
from app.services.workflow_routing.explicit_selection import (
    list_published_workflow_definitions,
    resolve_workflow_selection_for_turn,
)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import phased_definition, reviewer_user

JIRA = "https://jira.example.test/jira"
PLATFORM_KEY = "incident-analysis"


async def _published_phased(db, admin: User, key: str, project_id: str | None) -> dict:
    created = await create_flow_definition(db, current_user=admin, payload={
        "key": key, "name": f"Workflow {key}", "project_id": project_id, "definition": phased_definition(),
    })
    return await publish_flow_definition_version(
        db, version_id=created["versions"][0]["id"], current_user=await reviewer_user(db)
    )


async def _workspace_with_connector(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    authorized = await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)
    tool = {"jira_auth_mode": "basic", "jira_url": JIRA, "jira_username": "sync", "jira_password": "pw", "jira_allowed_projects": ["OPS"]}
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, config=tool, is_active=True))
    await db.flush()
    config = validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], schedule_enabled=True)
    row = await configure_connector(db, authorized=authorized, config=config, actor_id=user_id)
    return workspace_id, user, authorized, row


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


def _profile(resolution: dict):
    return build_execution_profile(
        prompt="Draw the topology.",
        requested_agent_type="diagnosis",
        effective_agent_type="chat",
        execution_strategy="direct",
        execution_strategy_reason="strategy:test",
        routing_intent="diagnosis",
        routing_intent_confidence=1.0,
        routing_reason="intent:diagnosis_default",
        routing_intent_source="policy",
        workflow_id="",
        workflow_contract={},
        workflow_routing_policy_resolution=resolution,
    )


@pytest.mark.asyncio
async def test_project_soft_delete_deactivates_its_bindings_and_resolution_refuses_them(db):
    workspace_id, member, authorized, connector = await _workspace_with_connector(db)
    admin = await _admin(db)
    await _published_phased(db, admin, "ws-scoped-workflow", workspace_id)
    await db.commit()
    assert connector.schedule_enabled is True

    await delete_project_for_admin(db, project_id=workspace_id, actor=admin)
    await db.commit()

    row = await db.get(KnowledgeSourceConnector, connector.id)
    assert (row.state, row.schedule_enabled, row.schedule_owner_id, row.next_scheduled_at) == ("paused", False, None, None)
    actions = set((await db.execute(select(AuditLog.action).where(AuditLog.user_id == admin.id))).scalars())
    assert {"project.soft_deleted", "knowledge.connector.deactivate"} <= actions

    resolution = await resolve_workflow_selection_for_turn(
        db, workflow_key="ws-scoped-workflow", user_message="Draw the topology.", project_id=workspace_id
    )
    assert resolution["status"] == "project_inactive"
    profile = _profile(resolution)
    assert (profile.status, profile.decision_source) == ("denied", "project_inactive")
    with pytest.raises(SyncRefusedError) as refused:
        await run_connector(db, runtime=build_runtime()[0], authorized=authorized, row=row, actor_id=member.id)
    assert refused.value.reason == "workspace_inactive"
    with pytest.raises(ConnectorError) as refused_config:
        await configure_connector(
            db,
            authorized=authorized,
            config=validate_config(connector_key="ops", kind="jira", project_keys=["OPS"]),
            actor_id=member.id,
        )
    assert refused_config.value.reason == "workspace_inactive"


@pytest.mark.asyncio
async def test_a_workflow_scoped_to_an_archived_project_is_not_listed(db):
    workspace_id = await seed_workspace(db)
    admin = await _admin(db)
    await _published_phased(db, admin, "archived-ws-workflow", workspace_id)
    project = await db.get(Project, workspace_id)
    project.is_active = False
    await db.flush()

    listed = {item["key"] for item in await list_published_workflow_definitions(db, project_id=workspace_id)}
    assert "archived-ws-workflow" not in listed
    assert PLATFORM_KEY in listed


@pytest.mark.asyncio
async def test_delete_connector_stops_it_keeps_sources_and_is_audited(db):
    workspace_id, member, authorized, connector = await _workspace_with_connector(db)
    db.add(KnowledgeSourceSyncRun(connector_id=connector.id, project_id=workspace_id, state="completed"))
    db.add(
        KnowledgeSourceSyncItem(
            connector_id=connector.id, project_id=workspace_id, external_id="1", source_key="jira.ops.1",
            source_id=str(uuid.uuid4()), state="ingested", last_outcome="ingested",
        )
    )
    await db.flush()

    outcome = await delete_connector(db, authorized=authorized, connector_key="ops", actor_id=member.id)

    assert outcome == {
        "state": "deleted", "connector_key": "ops", "kind": "jira",
        "retained_sources": 1, "removed_sync_items": 1, "removed_runs": 1,
    }
    assert await db.get(KnowledgeSourceConnector, connector.id) is None
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "knowledge.connector.delete"))).scalar_one()
    assert audit.details["workspace_id"] == workspace_id


@pytest.mark.asyncio
async def test_delete_connector_route_requires_an_author_and_names_a_missing_connector(db):
    workspace_id, member, _authorized, connector = await _workspace_with_connector(db)
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))

    with pytest.raises(HTTPException) as denied:
        await delete_workspace_connector(workspace_id, "ops", current_user=reader, db=db)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        await delete_workspace_connector(workspace_id, "absent", current_user=member, db=db)
    assert missing.value.status_code == 404
    assert (await delete_workspace_connector(workspace_id, "ops", current_user=member, db=db))["state"] == "deleted"
    assert await db.get(KnowledgeSourceConnector, connector.id) is None


def _foreign_keys_on(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.mark.asyncio
async def test_delete_connector_respects_foreign_keys(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    sa.event.listen(engine.sync_engine, "connect", _foreign_keys_on)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            workspace_id, member, authorized, connector = await _workspace_with_connector(db)
            db.add(KnowledgeSourceSyncRun(connector_id=connector.id, project_id=workspace_id, state="completed"))
            db.add(
                KnowledgeSourceSyncItem(
                    connector_id=connector.id, project_id=workspace_id, external_id="1", source_key="jira.ops.1",
                    state="ingested", last_outcome="ingested",
                )
            )
            await db.commit()

            outcome = await delete_connector(db, authorized=authorized, connector_key="ops", actor_id=member.id)

            assert (outcome["removed_sync_items"], outcome["removed_runs"]) == (1, 1)
            assert (await db.execute(select(KnowledgeSourceConnector))).first() is None
    finally:
        await engine.dispose()
