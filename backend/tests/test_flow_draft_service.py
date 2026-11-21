"""Draft snapshots preserve published execution and reject stale editor saves."""

import copy

import pytest
from sqlalchemy import select

from app.models import AuditLog, FlowDefinitionVersion, User
from app.services.auth import create_access_token
from tests.knowledge_evidence_seed_support import seed_workspace


def definition(label="Original"):
    return {
        "schema_version": "2.0",
        "nodes": [{"id": "start", "type": "trigger", "label": label},
                  {"id": "end", "type": "output"}],
        "edges": [{"source_node_id": "start", "target_node_id": "end", "source_field": "request", "target_field": "result"}],
    }


async def create(client, headers):
    response = await client.post("/api/v1/flows", headers=headers, json={
        "key": "draft-save-acceptance", "name": "Draft save", "definition": definition(),
    })
    assert response.status_code == 200, response.text
    return response.json()


def payload(flow, label="Edited"):
    return {"expected_latest_version_id": max(flow["versions"], key=lambda v: v["version"])["id"],
            "name": flow["name"], "description": "Edited description", "definition": definition(label)}


@pytest.mark.asyncio
@pytest.mark.parametrize("published", [False, True])
async def test_save_reload_preserves_prior_revision_and_published_pointer(client, auth_headers, db, published):
    flow = await create(client, auth_headers)
    original = copy.deepcopy(flow["versions"][0])
    if published:
        response = await client.post(f'/api/v1/flows/versions/{original["id"]}/publish', headers=auth_headers)
        assert response.status_code == 200, response.text
    response = await client.post(f'/api/v1/flows/{flow["id"]}/drafts', headers=auth_headers, json=payload(flow))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert len(saved["versions"]) == 2
    latest = max(saved["versions"], key=lambda v: v["version"])
    assert latest["version"] == 2 and latest["status"] == "draft"
    assert latest["definition"] == definition("Edited")
    assert saved["current_version_id"] == (original["id"] if published else latest["id"])
    old = await db.get(FlowDefinitionVersion, original["id"])
    assert old.definition_json == original["definition"]
    assert old.status == ("published" if published else "draft")
    workspace_id = await seed_workspace(db)  # the run starts in a Workspace
    run = await client.post(f'/api/v1/flows/versions/{latest["id"]}/run', headers=auth_headers,
                            json={"project_id": workspace_id, "initial_input": {}})
    assert run.status_code == 200, run.text
    assert run.json()["run"]["flow_definition_version_id"] == latest["id"]
    reload = await client.get(f'/api/v1/flows/{flow["id"]}', headers=auth_headers)
    assert reload.json()["versions"] == saved["versions"]
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "flow_draft_saved"))).scalars().all()
    assert any(a.details["version_id"] == latest["id"] for a in audits)
    stale = await client.post(f'/api/v1/flows/{flow["id"]}/drafts', headers=auth_headers, json=payload(flow, "Stale"))
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_draft_refuses_secret_missing_precondition_and_archived_flow(client, auth_headers):
    flow = await create(client, auth_headers)
    url = f'/api/v1/flows/{flow["id"]}/drafts'
    missing = payload(flow)
    del missing["expected_latest_version_id"]
    assert (await client.post(url, headers=auth_headers, json=missing)).status_code == 422
    secret = payload(flow)
    secret["definition"]["nodes"][0]["config"] = {"api_key": "never-persist-this"}
    assert (await client.post(url, headers=auth_headers, json=secret)).status_code == 422
    await client.post(f'/api/v1/flows/{flow["id"]}/archive', headers=auth_headers)
    assert (await client.post(url, headers=auth_headers, json=payload(flow))).status_code == 409


@pytest.mark.asyncio
async def test_draft_requires_admin(client, auth_headers, db):
    flow = await create(client, auth_headers)
    url = f'/api/v1/flows/{flow["id"]}/drafts'
    assert (await client.post(url, json=payload(flow))).status_code == 401
    user = User(username="draft-reader", email="draft-reader@example.test", password_hash="!", is_active=True)
    db.add(user)
    await db.commit()
    token = create_access_token(user.id)
    response = await client.post(url, json=payload(flow), headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
