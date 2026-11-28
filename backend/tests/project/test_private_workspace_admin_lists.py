from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, OutboundWebhook, OutboundWebhookDelivery, User
from app.models.integration.webhook import Webhook
from app.services.engineering_knowledge.graph_store_writes import upsert_engineering_knowledge_node
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import changed, snapshot
from tests.workspace_id_route_support import answer_text

pytestmark = pytest.mark.asyncio

HIDDEN = "foreign-private-object"
SHARED = "shared-workspace-object"
OWN = "own-private-object"


async def _setup(db) -> tuple[User, User, dict[str, str]]:
    owner = await user_named(db, f"lists-owner-{uuid.uuid4().hex[:6]}")
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    workspaces = {HIDDEN: (await ensure_private_workspace(db, owner)).id, SHARED: await seed_workspace(db),
                  OWN: (await ensure_private_workspace(db, admin)).id}
    await db.commit()
    return admin, owner, workspaces


async def test_the_engineering_knowledge_graph_list_leaves_out_a_foreign_private_workspace(client, db):
    admin, _owner, workspaces = await _setup(db)
    for marker, workspace_id in workspaces.items():
        await upsert_engineering_knowledge_node(db, node_type="decision", node_key=marker, display_name=marker,
                                                scope_type="workspace", scope_id=workspace_id)
    await db.commit()
    url = "/admin/chat/api/panel/engineering-knowledge/graph/nodes"
    listed = await client.get(url, headers=bearer(admin.id), params={"limit": 100})
    assert listed.status_code == 200, listed.text[:300]
    assert HIDDEN not in listed.text and SHARED in listed.text and OWN in listed.text
    scoped = {kind: await client.get(url, headers=bearer(admin.id), params={"scope_id": workspace_id})
              for kind, workspace_id in (("private", workspaces[HIDDEN]), ("unknown", str(uuid.uuid4())))}
    assert scoped["private"].json()["items"] == scoped["unknown"].json()["items"] == []
    assert scoped["private"].json()["total"] == scoped["unknown"].json()["total"] == 0
    assert listed.json()["stats"] == scoped["private"].json()["stats"]


async def test_a_bulk_definition_export_leaves_out_private_workspaces(client, db):
    admin, owner, workspaces = await _setup(db)
    for marker, workspace_id in workspaces.items():
        db.add(AgentDefinition(name=marker, owner_id=owner.id if marker == HIDDEN else admin.id,
                               project_id=workspace_id))
    await db.commit()
    for export_type in ("agent_definitions", "task_definitions"):
        job = await client.post("/api/v1/data/exports", headers=bearer(admin.id), json={
            "export_type": export_type, "scope_type": "global", "format": "json"})
        assert job.status_code in (200, 201), job.text[:300]
        blob = (await client.get(f"/api/v1/data/exports/{job.json()['id']}/download", headers=bearer(admin.id))).text
        assert HIDDEN not in blob
        if export_type == "agent_definitions":
            assert SHARED in blob
    missing_id = await client.post("/api/v1/data/exports", headers=bearer(admin.id), json={
        "export_type": "agent_definitions", "scope_type": "project", "format": "json"})
    assert missing_id.status_code == 400


async def _outbound(db, admin: User, owner: User, workspaces: dict[str, str]) -> dict[str, str]:
    ids = {}
    for marker, workspace_id in workspaces.items():
        row = OutboundWebhook(project_id=workspace_id, created_by=owner.id if marker == HIDDEN else admin.id,
                              name=marker, url="https://hooks.example.test/in", secret_hash="x", encrypted_secret="x")
        db.add(row)
        await db.flush()
        db.add(OutboundWebhookDelivery(webhook_id=row.id, project_id=workspace_id, event_type="task.completed",
                                       payload_json=f'{{"marker": "{marker}"}}'))
        ids[marker] = row.id
    global_row = OutboundWebhook(created_by=admin.id, name="global", url="https://hooks.example.test/all",
                                 secret_hash="x", encrypted_secret="x")
    db.add(global_row)
    await db.flush()
    db.add(OutboundWebhookDelivery(webhook_id=global_row.id, project_id=workspaces[HIDDEN],
                                   event_type="task.completed", payload_json=f'{{"marker": "{HIDDEN}-via-global"}}'))
    await db.commit()
    return ids


async def test_the_outbound_webhook_panel_lists_no_foreign_private_destination_or_delivery(client, db):
    admin, owner, workspaces = await _setup(db)
    await _outbound(db, admin, owner, workspaces)
    for path in ("/admin/chat/api/panel/outbound-webhooks", "/admin/chat/api/panel/outbound-webhook-deliveries"):
        response = await client.get(path, headers=bearer(admin.id))
        assert response.status_code == 200, response.text[:300]
        assert HIDDEN not in response.text and SHARED in response.text and OWN in response.text


@pytest.mark.parametrize(("method", "body"), [("PUT", {"url": "https://attacker.example.test/"}), ("DELETE", None)])
async def test_a_foreign_private_outbound_webhook_answers_like_a_missing_one(client, db, method, body):
    admin, owner, workspaces = await _setup(db)
    ids, headers = await _outbound(db, admin, owner, workspaces), bearer(admin.id)
    before, answers = await snapshot(db), {}
    for kind, webhook_id in (("private", ids[HIDDEN]), ("missing", str(uuid.uuid4()))):
        response = await client.request(method, f"/admin/chat/api/panel/outbound-webhooks/{webhook_id}",
                                        headers=headers, json=body)
        answers[kind] = (response.status_code, answer_text(response, webhook_id))
    db.expire_all()
    assert changed(before, await snapshot(db)) == []
    assert answers["private"] == answers["missing"] and answers["private"][0] == 404, answers
    for marker in (SHARED, OWN):
        kept = await client.request(method, f"/admin/chat/api/panel/outbound-webhooks/{ids[marker]}",
                                    headers=headers, json=body and {"name": f"{marker}-renamed"})
        assert kept.status_code == 200, (marker, kept.text[:300])


async def test_the_webhook_rest_api_hides_a_webhook_moved_into_a_foreign_private_workspace(client, db):
    admin, _owner, workspaces = await _setup(db)
    headers, ids = bearer(admin.id), {}
    for marker, workspace_id in workspaces.items():
        webhook = Webhook(project_id=workspace_id, owner_id=admin.id, name=marker)
        db.add(webhook)
        await db.flush()
        ids[marker] = webhook.id
    await db.commit()
    listed = await client.get("/api/v1/webhooks", headers=headers)
    assert listed.status_code == 200 and HIDDEN not in listed.text
    assert SHARED in listed.text and OWN in listed.text
    before = await snapshot(db)
    for path, method in (("/api/v1/webhooks/{id}/events", "GET"), ("/api/v1/webhooks/{id}", "DELETE")):
        answers = {}
        for kind, webhook_id in (("private", ids[HIDDEN]), ("missing", str(uuid.uuid4()))):
            response = await client.request(method, path.format(id=webhook_id), headers=headers)
            answers[kind] = (response.status_code, answer_text(response, webhook_id))
        assert answers["private"] == answers["missing"] and answers["private"][0] == 404, (path, answers)
    db.expire_all()
    assert changed(before, await snapshot(db)) == []
    events = await client.get(f"/api/v1/webhooks/{ids[SHARED]}/events", headers=headers)
    assert events.status_code == 200, events.text[:300]
