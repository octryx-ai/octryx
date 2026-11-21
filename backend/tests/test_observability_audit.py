"""Observability O5: the audit log lists administrative changes only, one event per change."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.audit_trail.timeline import list_audit
from app.services.exec_policy.policy_config import normalize_exec_policy_config
from tests.conftest import ADMIN_PASSWORD
from tests.observability_support import admin_user, call_as, user_with_role


@pytest.mark.asyncio
async def test_only_administrative_changes_are_listed_with_a_category(db):
    admin = await admin_user(db)
    marker = uuid.uuid4().hex[:8]
    rows = {
        f"admin.provider.model.updated.{marker}": "Runtime & models",
        f"policy_engine.published.{marker}": "Governance",
        f"auth.login.succeeded.{marker}": "Access & identity",
        f"admin.connector.saved.{marker}": "Connections & secrets",
        f"project.soft_deleted.{marker}": "Data",
        # the coding engine settings (Claude Code or Codex): platform, Workspace and a person's own choice
        f"admin.agent_gateway.default_engine_updated.{marker}": "Runtime & models",
        f"admin.agent_gateway.engines_updated.{marker}": "Runtime & models",
        f"user.agent_engine_updated.{marker}": "Runtime & models",
        f"prompt_catalog.{marker}.seed": None,
        f"knowledge.connector.run.{marker}": None,
        f"flow.node_started.{marker}": None,
        f"POST /api/v1/workspaces/{{id}}/knowledge/search?{marker}": None,
    }
    for action in rows:
        db.add(AuditLog(user_id=admin.id, action=action, resource_type="test", details={}))
    db.add(AuditLog(user_id=admin.id, action=f"agent_definition.write.{marker}", resource_type="agent",
                    details={"writer_class": "bootstrap"}))
    await db.commit()

    listed = {item["change"]: item["category"] for item in (await list_audit(db, query=marker, page_size=100))["items"]}

    assert listed == {action: category for action, category in rows.items() if category}
    governance = await list_audit(db, query=marker, category="Governance")
    assert [item["change"] for item in governance["items"]] == [f"policy_engine.published.{marker}"]


@pytest.mark.asyncio
async def test_a_login_is_one_event_and_generic_rows_carry_no_identifiers(client, db):
    client.cookies.clear()
    response = await client.post("/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 200
    actions = [row.action for row in (await db.execute(select(AuditLog).where(
        AuditLog.action.in_(["auth.login.succeeded", "POST /api/v1/auth/login"])))).scalars()]
    assert "auth.login.succeeded" in actions
    assert "POST /api/v1/auth/login" not in actions, "the domain event is the one login event"
    admin = await admin_user(db)
    session_id = str(uuid.uuid4())
    await call_as(client, "POST", f"/api/v1/sessions/{session_id}/not-a-route", admin)
    generic = (await db.execute(select(AuditLog).where(AuditLog.resource_type == "api"))).scalars().all()
    assert not any(session_id in row.action for row in generic)
    assert any(row.action == "POST /api/v1/sessions/{id}/not-a-route" and row.details["path"].endswith("not-a-route")
               for row in generic)


@pytest.mark.asyncio
async def test_audit_routes_are_admin_only_and_the_export_is_audited(client, db):
    admin = await admin_user(db)
    viewer = await user_with_role(db, "viewer")
    assert (await call_as(client, "GET", "/api/v1/observability/audit", viewer)).status_code == 403
    assert (await call_as(client, "POST", "/api/v1/observability/audit/export", viewer)).status_code == 403
    listed = await call_as(client, "GET", "/api/v1/observability/audit?window_days=7", admin)
    assert listed.status_code == 200 and listed.json()["categories"][0] == "Access & identity"
    exported = await call_as(client, "POST", "/api/v1/observability/audit/export", admin)
    assert exported.status_code == 200 and exported.text.startswith("time,actor,category,change")
    events = (await db.execute(select(AuditLog).where(AuditLog.action == "observability.audit.exported"))).scalars().all()
    assert len(events) == 1 and events[0].user_id == admin.id


def test_the_placebo_audit_fields_are_dropped_from_exec_policies():
    normalized = normalize_exec_policy_config({"audit_level": "verbose", "audit_required_actions": ["tool_call"]})
    assert "audit_level" not in normalized and "audit_required_actions" not in normalized
