from __future__ import annotations

import uuid

from app.models import ConnectorWatcher
from app.services.project.private_workspace import ensure_private_workspace
from app.services.secret import set_secret_value
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.support.connector_watchers_support import _create_watcher
from tests.workspace_id_route_inventory import changed, snapshot
from tests.workspace_id_route_support import answer_text, refusal_code

EVENT = {"event_type": "jira.issue.updated", "external_id": "OCX-7", "actor": "sample-actor"}


def _answer(response) -> tuple:
    return response.status_code, refusal_code(response), answer_text(response)


async def _post(client, watcher_id: str, secret: str | None = None):
    headers = {"X-Watcher-Secret": secret} if secret is not None else {}
    return await client.post(f"/api/v1/connector-watchers/{watcher_id}/webhook", headers=headers, json=EVENT)


async def _refused_without_writes(client, db, watcher_id: str, secret: str | None):
    before = await snapshot(db)
    response = await _post(client, watcher_id, secret)
    db.expire_all()
    # Verifying a stored webhook secret is a secret read, which WP-SA1 audits; nothing else is written.
    assert [table for table in changed(before, await snapshot(db)) if table != "secret_access_audit_log"] == []
    return response


async def test_a_shared_watcher_without_a_secret_refuses_events_like_a_wrong_secret(client, db, auth_headers):
    workspace = await seed_workspace(db)
    await db.commit()
    signed = await _create_watcher(client, auth_headers, project_id=workspace, name="signed")
    secretless = await _create_watcher(client, auth_headers, project_id=workspace, name="open",
                                       webhook_secret=None)
    assert secretless["secret_configured"] is False
    # The first anonymous request creates the audit principal its request log names.
    assert (await _post(client, str(uuid.uuid4()))).status_code == 404

    wrong = await _refused_without_writes(client, db, signed["id"], "wrong")
    missing = await _refused_without_writes(client, db, signed["id"], None)
    unsigned = await _refused_without_writes(client, db, secretless["id"], None)
    guessed = await _refused_without_writes(client, db, secretless["id"], "guess")
    assert wrong.status_code == 401
    assert _answer(missing) == _answer(unsigned) == _answer(guessed) == _answer(wrong)

    accepted = await _post(client, signed["id"], "test-secret")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "received"


async def test_a_private_watcher_without_a_secret_refuses_events_like_an_unknown_watcher(client, db):
    owner = await user_named(db, f"watcher-owner-{uuid.uuid4().hex[:6]}")
    workspace = (await ensure_private_workspace(db, owner)).id
    secretless, signed = (ConnectorWatcher(project_id=workspace, created_by=owner.id, connector_name="jira-cloud",
                                           provider_type="jira", name=name, mode="webhook", is_active=True)
                          for name in ("open", "signed"))
    db.add_all([secretless, signed])
    await db.flush()
    signed.secret_ref = (await set_secret_value(db, tool_name=f"connector_watcher:{signed.id}",
                                                field_name="webhook_secret", project_id=workspace,
                                                value="synthetic-secret")).id
    secretless_id, signed_id = secretless.id, signed.id
    await db.commit()

    unknown = await _post(client, str(uuid.uuid4()))
    assert unknown.status_code == 404
    for watcher_id, secret in ((secretless_id, None), (secretless_id, "guess"), (signed_id, None),
                               (signed_id, "wrong")):
        assert _answer(await _refused_without_writes(client, db, watcher_id, secret)) == _answer(unknown)

    accepted = await _post(client, signed_id, "synthetic-secret")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "received"
