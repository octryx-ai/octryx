"""Plugins: a plugin is installed by putting it into the image's plugin folder; an admin switches it on per
Workspace, and its skills, workflows, roles, MCP servers and pages reach only those Workspaces."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, FlowDefinition, McpServerRegistration, Project, User, UserProject
from app.models.runtime.work_role_model import WorkRole
from app.services.plugins.manifest import ManifestError
from app.services.plugins.manifest_parse import parse_manifest
from app.services.plugins.package import PackageError, files_from_folder, read_package
from tests.plugins_support import SHIPPED, _delivered, _in_image, _switch, _workspace_admin, uid
from tests.policy_engine_support import bearer


def _codes(error: Exception) -> set[str]:
    return {item["code"] for item in error.issues}


def test_the_manifest_refuses_what_an_installer_could_not_confirm():
    with pytest.raises(ManifestError) as refused:
        parse_manifest("""
apiVersion: octryx.ai/plugin/v1
id: NoDots
version: "1.0"
name: Bad
publisher: Someone
contributes:
  mcp_servers: [{name: tools, url: "https://tools.example.com/mcp"}]
  server: {image: "ghcr.io/acme/tools:latest"}
permissions:
  writes: [confluence]
""")
    assert {"manifest_id_invalid", "manifest_version_invalid", "manifest_egress_missing",
            "manifest_write_without_connection", "manifest_server_image_digest"} <= _codes(refused.value)


def test_a_workflow_that_writes_must_declare_it():
    files = files_from_folder(SHIPPED)
    files["workflows/writes.yaml"] = b"""
key: post-note
name: Post a note
definition:
  execution_kind: phased
  nodes:
    - {id: start, type: start, label: Start}
    - {id: post, type: platform_action, label: Post, config: {action: jira.comment, params: {text_from: review}}}
    - {id: done, type: outcome, label: Done, config: {outcome: done}}
  edges:
    - {id: a, source_node_id: start, target_node_id: post}
    - {id: b, source_node_id: post, target_node_id: done, when: succeeded}
    - {id: c, source_node_id: post, target_node_id: done, when: failed}
"""
    files["octryx-plugin.yaml"] = files["octryx-plugin.yaml"].replace(
        b"workflows: [workflows/release-notes.yaml]", b"workflows: [workflows/release-notes.yaml, workflows/writes.yaml]")
    with pytest.raises(PackageError) as refused:
        read_package(files)
    assert "workflow_write_undeclared" in _codes(refused.value)


def test_the_shipped_release_notes_plugin_is_valid():
    package = read_package(files_from_folder(SHIPPED))
    assert package.manifest.id == "octryx.release-notes"
    assert [s.name for s in package.skills] == ["release-notes", "release-readiness"]
    assert [w.key for w in package.workflows] == ["release-notes"] and package.workflows[0].writes == []
    assert package.manifest.ui["methods"] == ["jira_release_status", "list_jira_versions", "search_jira_tickets",
                                              "settings.get"]
    assert package.roles[0].key == "release_manager" and package.settings_schema["type"] == "object"


@pytest.mark.asyncio
async def test_a_workspace_admin_switches_an_image_plugin_on_in_their_workspace(client, db, tmp_path):
    user, ours, other = await _workspace_admin(db)
    user_id, ours_id, other_id = user.id, ours.id, other.id  # a refused switch rolls the shared session back
    member = User(id=uid(), username=f"dev_{uid()[:6]}", email=f"{uid()[:6]}@test.local", password_hash="x",
                  auth_source="local")
    db.add(member)
    await db.flush()
    db.add(UserProject(user_id=member.id, project_id=ours_id, role="member", granted_by=user_id))
    await db.commit()
    member_id = member.id

    assert (await _in_image(db, tmp_path, {"release-notes": files_from_folder(SHIPPED)}))["release-notes"][
        "outcome"] == "available"
    # In the image, on nowhere: its skills reach no Workspace yet.
    assert set((await _delivered(db, ours_id)).values()) == {"plugin_not_installed_here"}
    listed = (await client.get("/api/v1/plugins/available", params={"workspace_id": ours_id},
                               headers=bearer(member_id))).json()
    item = listed["plugins"][0]
    assert (item["plugin"], item["version"], item["active"], item["install_id"]) == (
        "octryx.release-notes", "1.1.0", False, None)
    assert [line["key"] for line in item["summary"]][:2] == ["plugins.summary.brings", "plugins.summary.pages"]
    assert item["summary"][0]["text"] == "Brings 2 skills, 1 workflow, 1 role"
    assert listed["viewer"]["can_activate"] is False  # a member sees, an admin switches
    refused = await _switch(client, member_id, "octryx.release-notes", ours_id)
    assert refused.json()["detail"]["code"] == "plugin_workspace_admin_only"

    on = await _switch(client, user_id, "octryx.release-notes", ours_id)
    assert on.status_code == 200, on.text
    body = on.json()
    assert (body["scope"], body["workspace_id"], body["status"], body["version"]) == (
        "workspace", ours_id, "active", "1.1.0")
    assert sorted(item["kind"] for item in body["contributions"]) == ["function", "role", "skill", "skill",
                                                                      "workflow"]
    assert await _delivered(db, ours_id) == {"release-notes": "", "release-readiness": ""}
    assert set((await _delivered(db, other_id)).values()) == {"plugin_not_installed_here"}
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == "release-notes"))).scalar_one()
    assert (flow.project_id, flow.status) == (ours_id, "published")
    flow_id = flow.id
    role = (await db.execute(select(WorkRole).where(WorkRole.key == "release_manager"))).scalar_one()
    assert role.project_id == ours_id
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "plugins.activated"))).scalar_one()
    assert (audit.user_id, audit.details["workspace_id"]) == (user_id, ours_id)
    # The Workspace lists its activation, never the image's own part.
    installs = (await client.get("/api/v1/plugins", params={"workspace_id": ours_id}, headers=bearer(user_id))).json()
    assert [p["id"] for p in installs["plugins"]] == [body["id"]]

    off = await _switch(client, user_id, "octryx.release-notes", ours_id, on=False)
    assert off.json()["status"] == "disabled"
    db.expire_all()
    assert set((await _delivered(db, ours_id)).values()) == {"plugin_not_installed_here"}
    assert (await db.get(FlowDefinition, flow_id)).is_active is False
    again = (await _switch(client, user_id, "octryx.release-notes", ours_id)).json()
    assert (again["id"], again["status"]) == (body["id"], "active")  # the same install, its settings kept
    unknown = await _switch(client, user_id, "acme.not-in-image", ours_id)
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "plugin_not_available"


@pytest.mark.asyncio
async def test_an_image_plugin_s_mcp_server_is_allowed_only_where_it_is_on(client, db, tmp_path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name=f"ws-{uid()[:6]}", is_active=True, config={})
    db.add(project)
    await db.commit()
    admin_id, project_id = admin.id, project.id
    await _in_image(db, tmp_path, {"price-check": {"octryx-plugin.yaml": b"""
apiVersion: octryx.ai/plugin/v1
id: acme.price-check
name: Price check
version: 0.1.0
publisher: ACME
contributes:
  mcp_servers: [{name: acme-prices, url: "https://prices.acme.example/mcp", tools: [get_price]}]
permissions:
  egress: [prices.acme.example]
"""}})
    server = (await db.execute(select(McpServerRegistration).where(
        McpServerRegistration.name == "acme-prices"))).scalar_one()
    assert (server.owner_scope, server.url) == ("platform", "https://prices.acme.example/mcp")

    async def allowed() -> list[str]:
        db.expire_all()
        project = await db.get(Project, project_id)
        return list(((project.config or {}).get("mcp_policy") or {}).get("enabled_servers") or [])

    assert (await _switch(client, admin_id, "acme.price-check", project_id)).status_code == 200
    assert await allowed() == ["acme-prices"]
    await _switch(client, admin_id, "acme.price-check", project_id, on=False)
    assert await allowed() == []
