"""A5: the Workflows page overview lists the phased workflows and flows with class, scope, use and last change."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User


@pytest.mark.asyncio
async def test_the_overview_lists_flows_as_the_runs_as_a_flow_kind(client, auth_headers, db):
    from app.models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion

    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    flow = FlowDefinition(key="incident-intake", name="Incident intake", created_by=user.id, status="draft")
    db.add(flow)
    await db.flush()
    version = FlowDefinitionVersion(
        flow_id=flow.id, version=1, created_by=user.id,
        definition_json={"schema_version": "2.0", "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "edges": []},
    )
    db.add(version)
    await db.flush()
    flow.current_version_id = version.id
    db.add(FlowDefinition(key="old-flow", name="Old", created_by=user.id, status="archived"))
    await db.commit()

    body = (await client.get("/api/v1/phased-workflows/overview", headers=auth_headers)).json()

    flows = {row["key"]: row for row in body["flows"]}
    assert "old-flow" not in flows
    assert flows["incident-intake"] | {"flow_id": "", "used": 0, "updated_at": ""} == {
        "flow_id": "", "key": "incident-intake", "title": "Incident intake", "description": "",
        "capability_class": "read_only", "node_count": 3, "scope": "Global", "project_id": None, "used": 0,
        "status": "draft", "version": 1, "version_status": "draft", "test_flow": False, "execution_kind": "flow",
        "is_active": True, "updated_at": "", "updated_by": user.display_name or user.username,
    }
    assert flows["incident-intake"]["updated_at"].endswith("Z")
    # A switched-off workflow stays listed with its switch (an admin switches it on again); an archived one leaves.
    flow.is_active = False
    await db.commit()
    body = (await client.get("/api/v1/phased-workflows/overview", headers=auth_headers)).json()
    assert {row["key"]: row for row in body["flows"]}["incident-intake"]["is_active"] is False


@pytest.mark.asyncio
async def test_the_list_says_who_changed_a_workflow_last_and_counts_phased_runs(client, auth_headers, db):
    from datetime import timedelta

    from app.models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion
    from app.models.runtime.workflow_run import WorkflowRun
    from app.time_utils import utc_now

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    editor = User(username="flow-editor", email="flow-editor@example.test", password_hash="x", display_name="Fay Editor")
    db.add(editor)
    await db.flush()
    flow = FlowDefinition(key="phased-intake", name="Phased intake", created_by=admin.id, status="published")
    db.add(flow)
    await db.flush()
    definition = {"schema_version": "2.0", "execution_kind": "phased", "nodes": [{"id": "a"}], "edges": []}
    published = FlowDefinitionVersion(
        flow_id=flow.id, version=1, created_by=admin.id, status="published", definition_json=definition,
        created_at=utc_now() - timedelta(days=3),
    )
    # A saved layout is a newer draft by someone else: the list names that change.
    layout = FlowDefinitionVersion(flow_id=flow.id, version=2, created_by=editor.id, definition_json=definition)
    db.add_all([published, layout])
    await db.flush()
    flow.current_version_id = published.id
    run = {"workflow_kind": "phased", "workflow_key": flow.key, "requested_by": admin.id}
    db.add_all([
        WorkflowRun(**run, flow_definition_version_id=published.id),
        WorkflowRun(**run, flow_definition_version_id=layout.id),
        WorkflowRun(**run, flow_definition_version_id=published.id, created_at=utc_now() - timedelta(days=45)),
    ])
    await db.commit()

    body = (await client.get("/api/v1/phased-workflows/overview", headers=auth_headers)).json()

    row = {item["key"]: item for item in body["flows"]}["phased-intake"]
    assert (row["execution_kind"], row["version"], row["used"]) == ("phased", 1, 2)  # runs in the 30-day window only
    assert row["updated_by"] == "Fay Editor"
    assert row["updated_at"] > published.created_at.isoformat()  # the layout draft, not the published version


def test_only_the_flagged_acceptance_fixture_is_a_test_flow():
    from types import SimpleNamespace

    from app.services.workflow_runs.overview_flows import is_test_flow

    assert is_test_flow(SimpleNamespace(publish_metadata={"test_fixture": True})) is True
    assert is_test_flow(SimpleNamespace(publish_metadata={})) is False
    assert is_test_flow(None) is False
