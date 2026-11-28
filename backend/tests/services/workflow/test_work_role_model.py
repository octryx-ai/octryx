"""Extensible work roles: functions, roles, assignments to people, groups and SSO claims, the effective permission,
the per-Workspace switch, the audit log and the admin API."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select, text

from app.models import IdentityProvider, UserIdentity
from app.models.runtime.work_role_model import WorkRole, WorkRoleAssignment, WorkRoleAuditEvent, WorkRoleFunction
from app.services.oidc_claims import resolve_identity_claims
from app.services.work_role_model.effective import effective_permission
from app.services.work_role_model.grant_checks import NO_ROLE_EN, connection_refusal, tool_refusal
from app.services.work_role_model.seeds import SEED_FUNCTIONS, SEED_ROLES, ensure_seed_catalog
from app.services.work_role_model.tool_sets import ToolSetError, entry_matches, normalize_entries
from tests.alembic_model_parity_support import migrated_database
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/work-roles"
def _seeded_catalog(connection) -> tuple[list, list]:
    functions = connection.execute(text(
        "SELECT key, name, description, tools_json FROM work_role_functions WHERE built_in ORDER BY key")).all()
    roles = connection.execute(text(
        "SELECT r.key, r.name, r.description, f.key FROM work_roles r "
        "JOIN work_role_function_links l ON l.role_id = r.id JOIN work_role_functions f ON f.id = l.function_id "
        "WHERE r.built_in ORDER BY r.key, f.key")).all()
    return functions, roles


def test_a_fresh_install_starts_with_exactly_the_seed_catalog(tmp_path):
    with migrated_database("sqlite", tmp_path) as database:
        functions, links = database.run(_seeded_catalog)
    assert [(key, name, description, json.loads(tools) if isinstance(tools, str) else tools)
            for key, name, description, tools in functions] == sorted(
        [(seed.key, seed.name, seed.description, list(seed.tools)) for seed in SEED_FUNCTIONS])
    roles: dict = {}
    for key, name, description, function in links:
        roles.setdefault((key, name, description), []).append(function)
    assert {role: sorted(keys) for role, keys in roles.items()} == {
        (seed.key, seed.name, seed.description): sorted(seed.functions) for seed in SEED_ROLES}
    legacy = {"product_manager", "engineer", "sre", "incident_lead", "support_agent", "agile_lead", "doc_owner"}
    assert legacy <= {seed.key for seed in SEED_ROLES}


def test_tool_set_entries_match_names_globs_risks_and_connectors():
    assert entry_matches("risk:read", "get_jira_ticket")
    assert not entry_matches("risk:read", "create_jira_ticket")
    assert entry_matches("connector:*:write", "create_jira_ticket")
    assert entry_matches("connector:jira", "get_jira_ticket")
    assert not entry_matches("connector:confluence", "get_jira_ticket")
    assert entry_matches("work_item_*", "work_item_create") and not entry_matches("work_item_*", "board_post")
    assert normalize_entries(["risk:read", "risk:read", " x_tool "]) == ["risk:read", "x_tool"]
    with pytest.raises(ToolSetError):
        normalize_entries(["risk:everything"])


async def _workspace_with_member(db):
    await ensure_seed_catalog(db)
    workspace = await seed_workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member")
    await db.commit()
    return workspace, member


async def _role(db, key):
    return (await db.execute(select(WorkRole).where(WorkRole.key == key, WorkRole.project_id.is_(None)))).scalar_one()


async def _switch_on(client, db, admin, workspace):
    response = await client.put(f"{BASE}/workspaces/{workspace}/settings",
                                json={"role_based_tools": True, "expected_version": 1}, headers=bearer(admin))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_switch_off_changes_nothing_and_no_role_means_no_tools_once_it_is_on(client, db):
    workspace, member = await _workspace_with_member(db)
    grant = await effective_permission(db, member, workspace)
    assert grant.unrestricted and tool_refusal(grant, "create_jira_ticket") is None

    admin = await make_user(db, admin=True)
    await _switch_on(client, db, admin, workspace)
    grant = await effective_permission(db, member, workspace)
    refusal = tool_refusal(grant, "get_jira_ticket")
    assert refusal["code"] == "work_role_none" and refusal["error"] == NO_ROLE_EN
    assert "Workspace admin" in refusal["who_can_change"]
    assert (await effective_permission(db, admin, workspace)).unrestricted


@pytest.mark.asyncio
async def test_a_developer_writes_through_connectors_but_does_not_decide_as_product_owner(client, db):
    workspace, member = await _workspace_with_member(db)
    admin = await make_user(db, admin=True)
    await _switch_on(client, db, admin, workspace)
    developer = await _role(db, "engineer")
    created = await client.post(f"{BASE}/workspaces/{workspace}/assignments", headers=bearer(admin),
                                json={"role_id": developer.id, "subject": {"kind": "user", "user_id": member}})
    assert created.status_code == 201, created.text
    grant = await effective_permission(db, member, workspace)
    assert [role.key for role in grant.roles] == ["engineer"]
    assert tool_refusal(grant, "create_jira_ticket") is None and tool_refusal(grant, "get_jira_ticket") is None
    refused = tool_refusal(grant, "change_plan_decide")
    assert refused["code"] == "role_tool_not_granted" and "Developer" in refused["error"]
    assert not grant.has_function("decide_as_po")
    duplicate = await client.post(f"{BASE}/workspaces/{workspace}/assignments", headers=bearer(admin),
                                  json={"role_id": developer.id, "subject": {"kind": "user", "user_id": member}})
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "assignment_exists"


@pytest.mark.asyncio
async def test_sso_group_and_sso_role_assignments_follow_the_last_sign_in(client, db):
    workspace, member = await _workspace_with_member(db)
    admin = await make_user(db, admin=True)
    provider = IdentityProvider(name=f"Entra {uuid.uuid4().hex[:6]}", claim_mappings_json={})
    db.add(provider)
    await db.flush()
    identity = UserIdentity(user_id=member, provider_id=provider.id, subject=uuid.uuid4().hex,
                            sso_groups_json=["shop-developers"], sso_roles_json=["Release-Manager"])
    db.add(identity)
    await db.commit()
    po = await _role(db, "product_manager")
    viewer = await _role(db, "viewer")
    for role, subject in ((viewer, {"kind": "sso_group", "value": "shop-developers"}),
                          (po, {"kind": "sso_role", "value": "Release-Manager", "provider_id": provider.id})):
        response = await client.post(f"{BASE}/workspaces/{workspace}/assignments", headers=bearer(admin),
                                     json={"role_id": role.id, "subject": subject})
        assert response.status_code == 201, response.text
    grant = await effective_permission(db, member, workspace)
    assert {role.key for role in grant.roles} == {"viewer", "product_manager"}
    assert "decide_as_po" in grant.functions
    via = next(role.via for role in grant.roles if role.key == "product_manager")
    assert via[0]["kind"] == "sso_role"

    identity.sso_roles_json = []
    await db.commit()
    grant = await effective_permission(db, member, workspace)
    assert {role.key for role in grant.roles} == {"viewer"}


def test_the_roles_claim_is_configurable_and_nested_paths_work():
    provider = IdentityProvider(name="Keycloak", claim_mappings_json={"roles": "realm_access.roles",
                                                                       "groups": "grp"})
    claims = resolve_identity_claims(provider, {"sub": "a", "grp": ["octryx-work"], "realm_access": {"roles": ["PO"]}})
    assert claims.sso_groups == ["octryx-work"] and claims.sso_roles == ["PO"]
    assert claims.external_groups == ["PO", "octryx-work"]


@pytest.mark.asyncio
async def test_delivery_per_connection_and_trusted_role_are_audited_opt_ins(client, db):
    workspace, member = await _workspace_with_member(db)
    admin = await make_user(db, admin=True)
    await _switch_on(client, db, admin, workspace)
    created = await client.post(f"{BASE}/roles", headers=bearer(admin), json={
        "key": "release_manager", "name": "Release manager", "function_keys": ["read", "decide_as_po"],
        "delivery_connections": "selected", "connection_ids": []})
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["trusted"] is False and role["function_keys"] == ["decide_as_po", "read"]
    assert role["functions"] == [{"key": "decide_as_po", "name": "Decide as product owner"},
                                 {"key": "read", "name": "Chat & knowledge"}]
    await client.post(f"{BASE}/workspaces/{workspace}/assignments", headers=bearer(admin),
                      json={"role_id": role["id"], "subject": {"kind": "user", "user_id": member}})
    grant = await effective_permission(db, member, workspace)
    refused = connection_refusal(grant, "create_jira_ticket", "conn-1")
    assert refused["code"] == "role_connection_not_granted" and refused["message"] == refused["error"]
    assert refused["setting"] and refused["who_can_change"]
    preview = (await client.get(f"{BASE}/workspaces/{workspace}/effective", params={"user_id": member},
                                headers=bearer(admin))).json()
    assert {"key": "decide_as_po", "name": "Decide as product owner"} in preview["functions_detail"]
    assert preview["write_connections"] == [] and preview["write_connections_detail"] == []

    no_reason = await client.put(f"{BASE}/roles/{role['id']}/trusted", headers=bearer(admin),
                                 json={"trusted": True, "expected_version": role["version"]})
    assert no_reason.status_code == 422 and no_reason.json()["detail"]["code"] == "reason_required"
    trusted = await client.put(f"{BASE}/roles/{role['id']}/trusted", headers=bearer(admin), json={
        "trusted": True, "reason": "release train", "expected_version": role["version"]})
    assert trusted.status_code == 200 and trusted.json()["trusted"] is True
    assert (await effective_permission(db, member, workspace)).trusted
    events = (await client.get(f"{BASE}/audit", params={"role_id": role["id"]}, headers=bearer(admin))).json()
    assert [event["action"] for event in events["events"]] == ["role.trusted_changed", "role.created"]
    assert events["events"][0]["before"] == {"trusted": False} and events["events"][0]["reason"] == "release train"


@pytest.mark.asyncio
async def test_admin_rules_built_ins_versions_and_members_who_would_lose_access(client, db):
    workspace, member = await _workspace_with_member(db)
    admin = await make_user(db, admin=True)
    page = await client.get(f"{BASE}/workspaces/{workspace}", headers=bearer(admin))
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["settings"]["role_based_tools"] is False
    assert [item["user_id"] for item in body["members_without_role"]] == [member]
    assert {role["key"] for role in body["roles"]} >= {"viewer", "engineer", "product_manager"}

    forbidden = await client.get(f"{BASE}/workspaces/{workspace}", headers=bearer(member))
    assert forbidden.status_code == 403 and forbidden.json()["detail"]["who_can_change"]
    stale = await client.put(f"{BASE}/workspaces/{workspace}/settings", headers=bearer(admin),
                             json={"role_based_tools": True, "expected_version": 7})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"

    workspace_admin = await _role(db, "workspace_admin")
    role_id, version = workspace_admin.id, workspace_admin.version
    lose = await client.patch(f"{BASE}/roles/{role_id}", headers=bearer(admin), json={
        "function_keys": ["read"], "expected_version": version})
    assert lose.status_code == 409 and lose.json()["detail"]["code"] == "role_keeps_function"
    delete = await client.delete(f"{BASE}/roles/{role_id}", headers=bearer(admin))
    assert delete.status_code == 409 and delete.json()["detail"]["code"] == "role_built_in"

    me = (await client.get(f"{BASE}/workspaces/{workspace}/me", headers=bearer(member))).json()
    assert me["enforced"] is False and me["empty_reason"] is None


@pytest.mark.asyncio
async def test_function_tool_sets_are_versioned_and_the_catalog_groups_by_connector_and_risk(client, db):
    await ensure_seed_catalog(db)
    await db.commit()
    admin = await make_user(db, admin=True)
    row = (await db.execute(select(WorkRoleFunction).where(WorkRoleFunction.key == "decide_as_po"))).scalar_one()
    function = type("F", (), {"id": row.id, "tools_version": row.tools_version})
    changed = await client.put(f"{BASE}/functions/{function.id}/tools", headers=bearer(admin), json={
        "tools": ["change_plan_decide", "workflow_decide", "create_jira_ticket"],
        "expected_tools_version": function.tools_version})
    assert changed.status_code == 200, changed.text
    assert changed.json()["tools_version"] == function.tools_version + 1
    stale = await client.put(f"{BASE}/functions/{function.id}/tools", headers=bearer(admin), json={
        "tools": [], "expected_tools_version": function.tools_version})
    assert stale.status_code == 409
    bad = await client.put(f"{BASE}/functions/{function.id}/tools", headers=bearer(admin), json={
        "tools": ["risk:all"], "expected_tools_version": function.tools_version + 1})
    assert bad.status_code == 422 and bad.json()["detail"]["entry"] == "risk:all"

    catalog = (await client.get(f"{BASE}/tool-catalog", params={"function_id": function.id},
                                headers=bearer(admin))).json()
    jira = next(group for group in catalog["groups"] if group["connector"] == "jira")
    assert any(tool["name"] == "create_jira_ticket" and tool["in_set"] for tool in jira["risks"]["write"])
    assert any(tool["name"] == "get_jira_ticket" and not tool["in_set"] for tool in jira["risks"]["read"])
    rows = (await db.execute(select(WorkRoleAuditEvent).where(WorkRoleAuditEvent.target_id == function.id))
            ).scalars().all()
    assert [row.action for row in rows] == ["function.tools_changed"]


@pytest.mark.asyncio
async def test_a_workspace_admin_assigns_but_only_platform_admins_edit_global_roles(client, db):
    workspace, member = await _workspace_with_member(db)
    ws_admin = await seed_member(db, workspace_id=workspace, role="admin")
    await db.commit()
    viewer = await _role(db, "viewer")
    viewer_id, viewer_version = viewer.id, viewer.version
    assigned = await client.post(f"{BASE}/workspaces/{workspace}/assignments", headers=bearer(ws_admin),
                                 json={"role_id": viewer_id, "subject": {"kind": "user", "user_id": member}})
    assert assigned.status_code == 201, assigned.text
    edit = await client.patch(f"{BASE}/roles/{viewer_id}", headers=bearer(ws_admin),
                              json={"name": "Reader", "expected_version": viewer_version})
    assert edit.status_code == 403 and edit.json()["detail"]["who_can_change"] == "a platform admin"
    revoked = await client.patch(f"{BASE}/workspaces/{workspace}/assignments/{assigned.json()['id']}",
                                 headers=bearer(ws_admin), json={"is_active": False, "expected_version": 1})
    assert revoked.status_code == 200 and revoked.json()["is_active"] is False
    row = await db.get(WorkRoleAssignment, assigned.json()["id"], populate_existing=True)
    assert row.version == 2
