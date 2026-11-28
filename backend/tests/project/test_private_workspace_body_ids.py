from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import User
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import changed, snapshot
from tests.workspace_id_route_support import answer_text, refusal_code

pytestmark = pytest.mark.asyncio

OWNER_MARKER = "body-id-owner"
SUBSCRIPTION = {"event_type": "problem.raised", "channel_type": "email", "target": "team@example.test"}
TEMPLATE = {"name": "Approval email", "event_type": "approval.requested", "channel_type": "email",
            "body_template": "Ticket={{ payload.ticket_id }}"}
WRITES = (
    ("/admin/chat/api/panel/agent-groups", {"name": "group"}, "/admin/chat/api/panel/agent-groups/{id}"),
    ("/admin/chat/api/panel/code-repositories", {"name": "repo", "repo_root": "/srv/repo"},
     "/admin/chat/api/panel/code-repositories/{id}"),
    ("/admin/chat/api/panel/webhooks", {"name": "hook"}, "/admin/chat/api/panel/webhooks/{id}"),
    ("/api/v1/api-keys", {"name": "key"}, None),
    ("/admin/chat/api/panel/users/{admin}/api-keys", {"name": "key"}, None),
    ("/admin/chat/api/panel/budget-policies", {"name": "budget", "daily_request_limit": 10}, None),
    ("/admin/budget-policies", {"name": "budget", "daily_request_limit": 10}, None),
    ("/admin/notification-subscriptions", SUBSCRIPTION, "/admin/notification-subscriptions/{id}"),
    ("/admin/notification-templates", TEMPLATE, "/admin/notification-templates/{id}"),
)
IDS = [path for path, _body, _update in WRITES]


async def _setup(db) -> tuple[User, dict[str, str]]:
    owner = await user_named(db, f"{OWNER_MARKER}-{uuid.uuid4().hex[:6]}")
    foreign = await ensure_private_workspace(db, owner)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    own = await ensure_private_workspace(db, admin)
    await db.commit()
    return admin, {"private": foreign.id, "unknown": str(uuid.uuid4()), "shared": await seed_workspace(db),
                   "own": own.id}


async def _refused_alike(client, db, method: str, url: str, body: dict, workspaces: dict[str, str], headers) -> None:
    before = await snapshot(db)
    answers = {}
    for kind in ("private", "unknown"):
        response = await client.request(method, url, headers=headers, json={**body, "project_id": workspaces[kind]})
        assert OWNER_MARKER not in response.text, response.text[:300]
        answers[kind] = (response.status_code, refusal_code(response), answer_text(response, workspaces[kind]))
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], url
    assert answers["private"] == answers["unknown"], answers
    assert answers["private"][:2] == (404, "project_not_found"), answers


@pytest.mark.parametrize(("path", "body", "update"), WRITES, ids=IDS)
async def test_a_platform_admin_creates_nothing_in_a_foreign_private_workspace(client, db, path, body, update):
    admin, workspaces = await _setup(db)
    await _refused_alike(client, db, "POST", path.format(admin=admin.id), body, workspaces, bearer(admin.id))


@pytest.mark.parametrize(("path", "body", "update"), [case for case in WRITES if case[2]],
                         ids=[case[0] for case in WRITES if case[2]])
async def test_a_platform_admin_moves_nothing_into_a_foreign_private_workspace(client, db, path, body, update):
    admin, workspaces = await _setup(db)
    created = await client.post(path, headers=bearer(admin.id), json={**body, "project_id": workspaces["shared"]})
    assert created.status_code in (200, 201), created.text[:300]
    url = update.format(id=created.json()["id"])
    await _refused_alike(client, db, "PUT", url, body, workspaces, bearer(admin.id))


@pytest.mark.parametrize(("path", "body", "update"), WRITES, ids=IDS)
async def test_a_platform_admin_still_writes_into_a_shared_and_their_own_private_workspace(client, db, path, body,
                                                                                         update):
    admin, workspaces = await _setup(db)
    for kind in ("shared", "own"):
        response = await client.post(path.format(admin=admin.id), headers=bearer(admin.id),
                                     json={**body, "project_id": workspaces[kind]})
        assert response.status_code in (200, 201), (kind, response.text[:300])


EK_NODE = {"node_type": "decision", "node_key": "use-postgres", "display_name": "Use Postgres"}
EK_SCOPED = (
    ("POST", "/admin/chat/api/panel/engineering-knowledge/graph/nodes", EK_NODE),
    ("POST", "/admin/chat/api/panel/engineering-knowledge/graph/edges",
     {"edge_type": "depends_on", "source_node_id": "n1", "target_node_id": "n2"}),
    ("POST", "/admin/chat/api/panel/engineering-knowledge/versions/v1/assignments", {}),
)


@pytest.mark.parametrize(("method", "path", "body"), EK_SCOPED, ids=[path for _m, path, _b in EK_SCOPED])
@pytest.mark.parametrize("scope_type", ["workspace", "project"])
async def test_an_engineering_knowledge_scope_naming_a_foreign_private_workspace_answers_like_an_unknown_one(
        client, db, method, path, body, scope_type):
    admin, workspaces = await _setup(db)
    before = await snapshot(db)
    answers = {}
    for kind in ("private", "unknown"):
        response = await client.request(method, path, headers=bearer(admin.id),
                                        json={**body, "scope_type": scope_type, "scope_id": workspaces[kind]})
        answers[kind] = (response.status_code, refusal_code(response), answer_text(response, workspaces[kind]))
    db.expire_all()
    assert changed(before, await snapshot(db)) == []
    assert answers["private"] == answers["unknown"] and answers["private"][:2] == (404, "project_not_found"), answers


async def test_an_engineering_knowledge_entity_read_scoped_to_a_foreign_private_workspace_answers_like_unknown(
        client, db):
    admin, workspaces = await _setup(db)
    answers = {}
    for kind in ("private", "unknown"):
        response = await client.get("/admin/chat/api/panel/engineering-knowledge/graph/entities/decision:x",
                                    headers=bearer(admin.id),
                                    params={"scope_type": "workspace", "scope_id": workspaces[kind]})
        answers[kind] = (response.status_code, answer_text(response, workspaces[kind]))
    assert answers["private"] == answers["unknown"] and answers["private"][0] == 404, answers


async def test_an_engineering_knowledge_node_is_still_written_into_a_shared_and_the_admins_own_workspace(client, db):
    admin, workspaces = await _setup(db)
    for kind in ("shared", "own"):
        response = await client.post("/admin/chat/api/panel/engineering-knowledge/graph/nodes",
                                     headers=bearer(admin.id),
                                     json={**EK_NODE, "scope_type": "workspace", "scope_id": workspaces[kind]})
        assert response.status_code == 200, (kind, response.text[:300])


async def _foreign_private_webhook(db, workspaces: dict[str, str]) -> str:
    from app.models.integration.webhook import Webhook, WebhookEvent
    from app.models.project.project import Project

    private = await db.get(Project, workspaces["private"])
    webhook = Webhook(project_id=private.id, owner_id=private.owner_user_id, name=f"{OWNER_MARKER}-hook")
    db.add(webhook)
    await db.flush()
    db.add(WebhookEvent(webhook_id=webhook.id, status="completed", parsed_message=OWNER_MARKER))
    await db.commit()
    return webhook.id


async def test_the_webhook_panel_leaves_out_a_webhook_of_a_foreign_private_workspace(client, db):
    admin, workspaces = await _setup(db)
    webhook_id = await _foreign_private_webhook(db, workspaces)
    for path in ("/admin/chat/api/panel/webhooks", "/admin/chat/api/panel/webhook-events"):
        response = await client.get(path, headers=bearer(admin.id))
        assert response.status_code == 200, response.text[:300]
        assert OWNER_MARKER not in response.text and webhook_id not in response.text


@pytest.mark.parametrize(("method", "path", "body"), [
    ("GET", "/admin/chat/api/panel/webhooks/{id}/events", None),
    ("POST", "/admin/chat/api/panel/webhooks/{id}/rotate-secret", None),
    ("POST", "/admin/chat/api/panel/webhooks/{id}/test", {"sample": "firing_error_rate"}),
    ("PUT", "/admin/chat/api/panel/webhooks/{id}", {"name": "renamed"}),
    ("DELETE", "/admin/chat/api/panel/webhooks/{id}", None),
])
async def test_a_webhook_of_a_foreign_private_workspace_answers_like_a_missing_one(client, db, method, path, body):
    admin, workspaces = await _setup(db)
    ids = {"private": await _foreign_private_webhook(db, workspaces), "missing": str(uuid.uuid4())}
    before = await snapshot(db)
    answers = {}
    for kind, webhook_id in ids.items():
        response = await client.request(method, path.format(id=webhook_id), headers=bearer(admin.id), json=body)
        assert OWNER_MARKER not in response.text, response.text[:300]
        answers[kind] = (response.status_code, answer_text(response, webhook_id))
    db.expire_all()
    assert changed(before, await snapshot(db)) == []
    assert answers["private"] == answers["missing"] and answers["private"][0] == 404, answers
