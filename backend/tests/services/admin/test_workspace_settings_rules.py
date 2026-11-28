"""The first editors for the Workspace's coding-tool rules, MCP servers and budget overrides, and
the Access check computed from the gates the platform runs."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import McpServerRegistration, Project, Role, User, UserRole
from app.services.admin.governance.admin_access_service import list_effective_access_diagnostics
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.mcp_access_policy import mcp_server_access_decision
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/admin/workspaces/{}"


async def _workspace(db, **config) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, config=config)
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_a_first_coding_edit_keeps_the_baseline_rules(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db)
    route = BASE.format(project.id) + "/coding"
    view = (await client.get(route, headers=bearer(admin))).json()
    assert [rule["id"] for rule in view["tool_rules"]] == [rule["id"] for rule in BASELINE_POLICY["tool_rules"]]
    rules = [*view["tool_rules"], {"id": "no-terraform-destroy", "kind": "command_prefix_denied",
                                   "prefix": ["terraform", "destroy"]}]
    saved = await client.put(route, headers=bearer(admin), json={"requires_governed_routing": True,
                                                                "tool_rules": rules, "client_deny": ["Bash(rm -rf:*)"]})
    assert saved.status_code == 200, saved.text
    await db.refresh(project)
    stored = project.config["agent_gateway_policy"]
    assert stored["requires_governed_routing"] is True and stored["client_permissions"]["deny"] == ["Bash(rm -rf:*)"]
    assert {"kubectl-requires-context", "no-terraform-destroy"} <= {rule["id"] for rule in stored["tool_rules"]}
    bad = await client.put(route, headers=bearer(admin), json={"requires_governed_routing": False,
                                                              "tool_rules": [{"id": "x", "kind": "nope"}]})
    assert bad.status_code == 422 and bad.json()["detail"]["reason"] == "unknown_rule_kind"


@pytest.mark.asyncio
async def test_mcp_servers_are_allowed_per_workspace_and_the_key_is_validated(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db)
    registration = McpServerRegistration(name="docs-search", owner_scope="platform", transport="stdio", is_active=True)
    db.add(registration)
    await db.commit()
    server_id = registration.id
    route = BASE.format(project.id) + "/mcp-servers"
    listed = (await client.get(route, headers=bearer(admin))).json()["servers"]
    assert next(item for item in listed if item["server_name"] == "docs-search")["allowed"] is False, "deny by default"
    saved = await client.put(f"{route}/{server_id}", headers=bearer(admin), json={"allowed": True})
    assert saved.status_code == 200, saved.text
    await db.refresh(project)
    assert mcp_server_access_decision("docs-search", project.config).allowed
    raw = await client.put(f"/api/v1/projects/{project.id}/config", headers=bearer(admin),
                           json={"mcp_policy": {"enabled_servers": ["bad name!"]}})
    assert raw.status_code == 400, "a registered key: validated on every write path"
    tools = await client.put(f"/api/v1/projects/{project.id}/config", headers=bearer(admin),
                             json={"mcp_policy": {"enabled_servers": ["docs-search"],
                                                  "selected_tools": {"docs-search": ["search"]}}})
    assert tools.status_code == 200, "Runtime's selected_tools is part of the validated shape"


@pytest.mark.asyncio
async def test_budget_overrides_set_and_go_back_to_inherit(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db)
    route = BASE.format(project.id) + "/budget"
    saved = await client.put(route, headers=bearer(admin),
                             json={"session_usd": 100, "request_usd": None, "per_person_daily_usd": 25})
    assert saved.status_code == 200, saved.text
    assert {key: saved.json()[key] for key in ("session_usd", "request_usd", "per_person_daily_usd")} == {
        "session_usd": 100.0, "request_usd": None, "per_person_daily_usd": 25.0}
    back = (await client.put(route, headers=bearer(admin),
                             json={"session_usd": None, "request_usd": None, "per_person_daily_usd": None})).json()
    assert {key: back[key] for key in ("session_usd", "request_usd", "per_person_daily_usd")} == {
        "session_usd": None, "request_usd": None, "per_person_daily_usd": None}
    await db.refresh(project)
    assert project.config["agent_gateway_policy"]["session_budget"] == {"per_user_daily_usd": 200}
    assert "runtime_cost_limits" not in project.config
    member = await make_user(db, admin=False)
    assert (await client.get(route, headers=bearer(member))).status_code == 404


@pytest.mark.asyncio
async def test_the_access_check_answers_with_the_platform_gates(db):
    no_login = await make_user(db, admin=False)
    role = Role(id=str(uuid.uuid4()), name=f"r{uuid.uuid4().hex[:6]}")
    db.add(role)
    await db.flush()
    db.add(UserRole(user_id=no_login, role_id=role.id))
    await db.commit()
    rows = {row["user"]["id"]: row for row in await list_effective_access_diagnostics(db)}
    effective = rows[no_login]["effective"]
    assert effective["can_use_chat"] is False, "an active account without auth:login cannot sign in"
    assert effective["can_open_admin_panel"] is False
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    assert rows[admin_id]["effective"] == {**rows[admin_id]["effective"], "can_use_chat": True,
                                           "can_open_admin_panel": True}


@pytest.mark.asyncio
async def test_session_permissions_by_role_are_set_on_the_coding_page(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db)
    route = BASE.format(project.id) + "/coding"
    view = (await client.get(route, headers=bearer(admin))).json()
    assert view["role_modes"] == {"viewer": "read_only", "member": "edit", "owner": "bypass", "admin": "bypass"}
    saved = await client.put(route, headers=bearer(admin), json={
        "requires_governed_routing": False, "tool_rules": view["tool_rules"], "client_deny": view["client_deny"],
        "role_modes": {**view["role_modes"], "member": "bypass", "viewer": "edit"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["role_modes"]["member"] == "bypass" and saved.json()["role_modes"]["viewer"] == "edit"
    bad = await client.put(route, headers=bearer(admin), json={
        "requires_governed_routing": False, "tool_rules": view["tool_rules"], "client_deny": view["client_deny"],
        "role_modes": {"member": "root"}})
    assert bad.status_code == 422
