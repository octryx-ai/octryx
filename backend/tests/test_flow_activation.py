"""An admin switches a shipped optional workflow (shipped, off by default) on and off."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.models import AuditLog, FlowDefinition, FlowDefinitionVersion, WorkflowRun
from app.services.flow_activation import AUDIT_ACTION
from app.services.workflow_runs.run_start import startable_workflows_for
from app.services.workflow_runs.seeding import seed_phased_workflows
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.policy_engine_support import bearer

TRIAGE = "jira-intake-triage"


async def _fresh_install(db) -> FlowDefinition:
    rows = (await db.execute(select(FlowDefinition).where(FlowDefinition.project_id.is_(None)))).scalars().all()
    ids = [row.id for row in rows]
    await db.execute(delete(FlowDefinitionVersion).where(FlowDefinitionVersion.flow_id.in_(ids)))
    await db.execute(delete(FlowDefinition).where(FlowDefinition.id.in_(ids)))
    await db.flush()
    await seed_phased_workflows(db, admin_user=await admin_user(db))
    await db.commit()
    return (await db.execute(select(FlowDefinition).where(FlowDefinition.key == TRIAGE))).scalar_one()


async def _keys(db) -> set[str]:
    return {item["key"] for item in await startable_workflows_for(db, project_id=None)}


@pytest.mark.asyncio
async def test_an_admin_switches_an_optional_workflow_on_and_off_and_each_start_reads_it(client, db, auth_headers):
    triage = await _fresh_install(db)
    assert not triage.is_active and TRIAGE not in await _keys(db)  # shipped, published, off
    flow_id, version = triage.id, triage.current_version_id

    on = await client.post(f"/api/v1/flows/{flow_id}/active", json={"active": True}, headers=auth_headers)
    assert on.status_code == 200, on.text
    assert on.json() == {"id": flow_id, "key": TRIAGE, "is_active": True}
    db.expire_all()
    assert TRIAGE in await _keys(db)
    assert (await db.get(FlowDefinition, flow_id)).current_version_id == version  # no new version, no draft

    admin = await admin_user(db)
    run = WorkflowRun(project_id=None, workflow_kind="phased", workflow_key=TRIAGE, title="t", requested_by=admin.id,
                      status="running")
    db.add(run)
    await db.commit()
    run_id = run.id
    off = await client.post(f"/api/v1/flows/{flow_id}/active", json={"active": False}, headers=auth_headers)
    assert off.status_code == 200 and off.json()["is_active"] is False
    db.expire_all()
    assert TRIAGE not in await _keys(db)
    assert (await db.get(WorkflowRun, run_id)).status == "running"  # only new starts stop

    await seed_phased_workflows(db, admin_user=admin)  # the next deploy keeps the admin's choice
    await db.commit()
    db.expire_all()
    assert not (await db.get(FlowDefinition, flow_id)).is_active
    audits = (await db.execute(select(AuditLog.details).where(AuditLog.action == AUDIT_ACTION,
                                                              AuditLog.resource_id == flow_id))).scalars().all()
    assert sorted((item["before"], item["after"]) for item in audits) == [(False, True), (True, False)]


@pytest.mark.asyncio
async def test_a_non_admin_an_archived_workflow_and_a_missing_value_are_refused(client, db, auth_headers):
    triage = await _fresh_install(db)
    workspace = await seed_workspace(db)
    owner = await seed_member(db, workspace_id=workspace, role="owner")
    await db.commit()
    url = f"/api/v1/flows/{triage.id}/active"
    assert (await client.post(url, json={"active": True}, headers=bearer(owner))).status_code == 403
    assert (await client.post(url, json={"active": "yes"}, headers=auth_headers)).status_code == 422
    assert (await client.post("/api/v1/flows/nope/active", json={"active": True}, headers=auth_headers)
            ).status_code == 404
    assert (await client.post(f"/api/v1/flows/{triage.id}/archive", headers=auth_headers)).status_code == 200
    refused = await client.post(url, json={"active": True}, headers=auth_headers)
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "flow_archived"
