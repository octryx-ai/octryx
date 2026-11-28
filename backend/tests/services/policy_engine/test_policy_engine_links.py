"""Policy UX: platform policies on the Workspace policy page, reference counts for connector cards."""

from __future__ import annotations

import uuid

import pytest

from app.models import ConnectorNamedConnection
from app.services.policy_engine.builder import render
from app.services.policy_engine.builder_model import model_from_json
from tests.factories import make_project
from tests.knowledge_evidence_seed_support import seed_member
from tests.policy_engine_support import BASE, bearer, make_user, publish


async def _workspace(db, level: str | None) -> str:
    return (await make_project(
        db,
        name=f"ws-{uuid.uuid4().hex[:6]}",
        config={"data_policy": {"classification": level}} if level else {},
        commit=True,
    )).id


def _builder(raw: dict) -> str:
    model, issues = model_from_json(raw)
    assert model is not None, issues
    return render(model)


@pytest.mark.asyncio
async def test_the_workspace_summary_lists_the_published_policies_that_apply_there(client, db):
    internal, confidential, other = await _workspace(db, "internal"), await _workspace(db, "confidential"), \
        await _workspace(db, "internal")
    member = await seed_member(db, workspace_id=internal, role="member")
    summary = f"/api/v1/workspaces/{internal}/policy-summary"
    before = (await client.get(summary, headers=bearer(member))).json()
    assert before["platform_policies"] == {"version": None, "items": []}

    texts = [
        _builder({"id": "a-only-internal-ws", "name": "Only here", "actions": ["use_seat"],
                  "where": {"workspaces": [internal]}}),
        _builder({"id": "b-confidential-up", "actions": ["call_model"],
                  "where": {"classification_at_least": "confidential"}}),
        f'@id("c-other-ws")\nforbid (principal, action == Action::"use_seat", resource)\n'
        f'when {{ context.workspace == Workspace::"{other}" }};',
        '@id("d-everywhere-conditions")\nforbid (principal, action == Action::"run_command", resource)\n'
        'when { resource.program == "rm" };',
        '@id("e-everywhere")\nforbid (principal in Role::"ops", action == Action::"write_connector", resource);',
    ]
    version = await publish(client, db, "\n\n".join(texts) + "\n")
    body = (await client.get(summary, headers=bearer(member))).json()["platform_policies"]
    assert body["version"] == version
    assert [item["id"] for item in body["items"]] == ["a-only-internal-ws", "d-everywhere-conditions", "e-everywhere"]
    first = body["items"][0]
    assert set(first) == {"id", "name", "description", "source", "sentence", "scope", "groups", "conditional"}
    assert first["name"] == "Only here" and first["source"] == "builder" and first["conditional"] is False
    assert "".join(seg["text"] for seg in first["sentence"]).startswith("Block everyone from using a personal seat in ")
    assert [item["conditional"] for item in body["items"][1:]] == [True, False]
    upper = (await client.get(f"/api/v1/workspaces/{confidential}/policy-summary",
                              headers=bearer(await make_user(db, admin=True)))).json()["platform_policies"]
    assert [item["id"] for item in upper["items"]] == ["b-confidential-up", "d-everywhere-conditions", "e-everywhere"]


@pytest.mark.asyncio
async def test_reference_counts_per_connector_and_connection(client, db):
    admin = await make_user(db, admin=True)
    connection = ConnectorNamedConnection(tool_name="servicenow", project_id=None, scope_key="global",
                                          name="primary", config={}, bound_scopes=[])
    db.add(connection)
    await db.commit()
    published = await publish(client, db, _builder({"id": "gone", "actions": ["read_connector"],
                                                    "what": {"families": ["jira"]}}) + "\n")
    texts = [
        _builder({"id": "on-primary", "actions": ["write_connector"], "where": {"connections": [connection.id]}}),
        _builder({"id": "jira-wide", "actions": ["write_connector"], "what": {"families": ["jira"]}}),
        _builder({"id": "sn-default", "actions": ["write_connector"], "what": {"families": ["servicenow"]},
                  "where": {"connections": ["default"]}}),
    ]
    draft = await client.post(f"{BASE}/policy-sets", json={"policies": "\n\n".join(texts) + "\n"}, headers=bearer(admin))
    assert draft.status_code == 201 and published
    body = (await client.get(f"{BASE}/policies/references", headers=bearer(admin))).json()
    assert {key: value["count"] for key, value in body["connectors"].items()} == {"jira": 1, "servicenow": 2}
    assert {key: value["count"] for key, value in body["connector_wide"].items()} == {"jira": 1}
    assert body["connections"][connection.id] == {"count": 1, "policies": [{"id": "on-primary", "name": "on-primary"}]}
    assert body["connections"]["default"]["count"] == 1
    assert "gone" not in str(body), "a policy removed in the draft is not counted"
    member = await make_user(db, admin=False)
    assert (await client.get(f"{BASE}/policies/references", headers=bearer(member))).status_code == 403
