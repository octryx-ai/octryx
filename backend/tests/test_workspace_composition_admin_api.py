"""The workspace composition admin API: seeded bindings and diagnostics, the runtime catalog and binding and policy updates."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget, Project
from tests.workspace_composition_admin_api_support import _create_workspace_fixture, _login_admin


@pytest.mark.asyncio
async def test_workspace_composition_api_lists_seeded_bindings_and_diagnostics(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]

    resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["workspace"]["id"] == project.id
    assert payload["summary"]["binding_counts"]["agent"] == 2
    assert payload["summary"]["binding_counts"]["runtime"] >= 1
    assert payload["assignment_controls"]["agent_assignment_mode"] == "all_installed"
    assert payload["assignment_controls"]["runtime_assignment_mode"] == "all_installed"
    assert payload["assignment_controls"]["available_agent_binding_keys"]
    assert payload["assignment_controls"]["available_runtime_binding_keys"]
    assert "compatibility_policy" not in payload["policy"]
    assert set(payload["diagnostics"]) == {"warnings"}


@pytest.mark.asyncio
async def test_workspace_composition_api_exposes_runtime_catalog_for_project_without_agents(client, db):
    await _login_admin(client)
    runtime_target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert runtime_target is not None
    project = Project(
        id=str(uuid.uuid4()),
        name=f"support-runtime-catalog-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    db.add(project)
    await db.commit()

    resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    runtime_bindings = [item for item in payload["bindings"] if item["capability_kind"] == "runtime"]
    catalog_binding = next(
        item for item in runtime_bindings if item["source_entity_id"] == runtime_target.id
    )
    assert catalog_binding["is_enabled"] is False
    assert catalog_binding["binding_status"] == "active"
    assert catalog_binding["policy_config"]["source"] == "control_plane_runtime_catalog"
    assert payload["assignment_controls"]["runtime_assignment_mode"] == "all_installed"


@pytest.mark.asyncio
async def test_workspace_composition_binding_update_rotates_kind_default_without_breaking_project_panel(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]

    initial = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition")
    assert initial.status_code == 200
    bindings = [item for item in initial.json()["bindings"] if item["capability_kind"] == "agent"]
    assert len(bindings) == 2

    first_update = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/bindings/{bindings[0]['id']}",
        json={"is_default": True, "display_name": "Primary Workspace Agent"},
    )
    assert first_update.status_code == 200, first_update.text

    second_update = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/bindings/{bindings[1]['id']}",
        json={"is_default": True},
    )
    assert second_update.status_code == 200, second_update.text
    payload = second_update.json()
    updated_bindings = [item for item in payload["bindings"] if item["capability_kind"] == "agent"]
    first_binding = next(item for item in updated_bindings if item["id"] == bindings[0]["id"])
    second_binding = next(item for item in updated_bindings if item["id"] == bindings[1]["id"])
    assert first_binding["is_default"] is False
    assert first_binding["display_name"] == "Primary Workspace Agent"
    assert second_binding["is_default"] is True
    assert payload["summary"]["default_binding_keys"]["agent"] == second_binding["binding_key"]

    legacy_panel = await client.get("/admin/chat/api/panel/projects")
    assert legacy_panel.status_code == 200
    listed = next(item for item in legacy_panel.json() if item["id"] == project.id)
    assert "project_agent_catalog" in listed
    assert "playbook_instances" not in listed


@pytest.mark.asyncio
async def test_workspace_composition_policy_update_validates_default_bindings(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]

    initial = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition")
    assert initial.status_code == 200
    runtime_binding = next(
        item
        for item in initial.json()["bindings"]
        if item["capability_kind"] == "runtime" and item["is_enabled"]
    )

    invalid = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/policy",
        json={"default_bindings": {"runtime": "missing-binding"}},
    )
    assert invalid.status_code == 400
    assert "unknown binding" in invalid.text

    valid = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/policy",
        json={
            "default_bindings": {"runtime": runtime_binding["binding_key"]},
            "delegation_policy": {"allow_coordinator": True, "max_child_fanout": 4},
            "routing_policy": {"enabled_intents": ["documentation", "diagnosis"]},
        },
    )
    assert valid.status_code == 200, valid.text
    payload = valid.json()
    assert payload["policy"]["default_bindings"]["runtime"] == runtime_binding["binding_key"]
    assert payload["policy"]["delegation_policy"]["max_child_fanout"] == 4
    assert payload["policy"]["routing_policy"]["enabled_intents"] == ["documentation", "diagnosis"]

    diagnostics = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/diagnostics")
    assert diagnostics.status_code == 200
    diagnostics_payload = diagnostics.json()
    assert diagnostics_payload["summary"]["default_binding_keys"]["runtime"] == runtime_binding["binding_key"]
