"""Settings rules: inherited daily budgets survive, Workspace admins may only tighten, scoped MCP lists,
visible tool policy, resolved MCP classification, and backup history naming deleted users."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import McpServerRegistration, Project
from app.services.agent_gateway.policy import load_workspace_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.data_classification.effect_rules import EffectRule, set_effect_rules
from app.services.data_transfer.backup import DELETED_USER, DELETED_WORKSPACE, backup_history
from app.services.mcp_access_policy import mcp_server_access_decision
from app.services.tool_approval.policy import effective_policy, set_platform_default
from tests.knowledge_evidence_seed_support import seed_member
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/admin/workspaces/{}"


async def _workspace(db, **config) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True, config=config)
    db.add(project)
    await db.commit()
    return project


@pytest.mark.asyncio
async def test_inheriting_the_daily_budget_keeps_the_platform_value_in_force(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db)
    project_id = project.id
    route = BASE.format(project_id) + "/budget"
    saved = await client.put(route, headers=bearer(admin),
                             json={"session_usd": 5, "request_usd": None, "per_person_daily_usd": None})
    assert saved.status_code == 200, saved.text
    assert saved.json()["per_person_daily_usd"] is None and saved.json()["platform"]["per_person_daily_usd"] == 200
    load = await load_workspace_policy(db, project_id)
    assert load.policy is not None and load.policy.daily_budget_usd == 200, "coding sessions keep a budget"


@pytest.mark.asyncio
async def test_a_workspace_owner_may_tighten_but_is_refused_loosening(client, db):
    project = await _workspace(db)
    project_id = project.id
    owner = await seed_member(db, workspace_id=project_id, role="owner")
    await db.commit()  # a refused save rolls the request's session back
    budget = BASE.format(project_id) + "/budget"
    coding = BASE.format(project_id) + "/coding"

    over = await client.put(budget, headers=bearer(owner),
                            json={"session_usd": 1_000_000, "request_usd": None, "per_person_daily_usd": None})
    assert over.status_code == 403 and over.json()["detail"]["code"] == "platform_admin_required"
    off = await client.put(budget, headers=bearer(owner),
                           json={"session_usd": 0, "request_usd": None, "per_person_daily_usd": None})
    assert off.status_code == 403, "0 turns the cap off: looser"
    assert (await client.put(budget, headers=bearer(owner),
                             json={"session_usd": None, "request_usd": None, "per_person_daily_usd": 500})).status_code == 403
    tighter = await client.put(budget, headers=bearer(owner),
                               json={"session_usd": 0.5, "request_usd": None, "per_person_daily_usd": 20})
    assert tighter.status_code == 200, tighter.text

    view = (await client.get(coding, headers=bearer(owner))).json()
    dropped = [rule for rule in view["tool_rules"] if rule["id"] != "no-force-push"]
    refused = await client.put(coding, headers=bearer(owner), json={**view, "tool_rules": dropped})
    assert refused.status_code == 403 and refused.json()["detail"]["path"] == "tool_rules.no-force-push"
    no_deny = await client.put(coding, headers=bearer(owner), json={**view, "client_deny": []})
    assert no_deny.status_code == 403
    added = [*view["tool_rules"], {"id": "no-terraform-destroy", "kind": "command_prefix_denied",
                                   "prefix": ["terraform", "destroy"]}]
    on = await client.put(coding, headers=bearer(owner), json={**view, "tool_rules": added,
                                                               "requires_governed_routing": True})
    assert on.status_code == 200, on.text
    back_off = await client.put(coding, headers=bearer(owner), json={**on.json(), "requires_governed_routing": False})
    assert back_off.status_code == 403 and back_off.json()["detail"]["path"] == "requires_governed_routing"
    assert BASELINE_POLICY["client_permissions"]["deny"][0] in on.json()["client_deny"]


@pytest.mark.asyncio
async def test_the_mcp_list_is_scoped_and_an_owner_only_switches_platform_servers_off(client, db):
    project = await _workspace(db, mcp_policy={"enabled_servers": ["docs-search"]})
    other = await _workspace(db)
    project_id, other_id = project.id, other.id
    db.add_all([
        McpServerRegistration(name="docs-search", owner_scope="platform", transport="stdio", is_active=True),
        McpServerRegistration(name="ticket-desk", owner_scope="platform", transport="stdio", is_active=True),
        McpServerRegistration(name="retired-tool", owner_scope="platform", transport="stdio", is_active=False),
        McpServerRegistration(name="their-own", owner_scope="workspace", workspace_id=other_id, transport="stdio",
                              is_active=True),
        McpServerRegistration(name="our-own", owner_scope="workspace", workspace_id=project_id, transport="stdio",
                              is_active=True),
    ])
    await db.commit()
    ids = {row.name: row.id for row in (await db.execute(select(McpServerRegistration))).scalars()}
    owner = await seed_member(db, workspace_id=project_id, role="owner")
    route = BASE.format(project_id) + "/mcp-servers"
    listed = await client.get(route, headers=bearer(owner))
    assert listed.status_code == 200, listed.text
    names = {item["server_name"] for item in listed.json()["servers"]}
    assert {"docs-search", "ticket-desk", "our-own"} <= names and not names & {"retired-tool", "their-own"}
    foreign = await client.put(f"{route}/{ids['their-own']}", headers=bearer(owner), json={"allowed": True})
    assert foreign.status_code in {403, 422}
    loosen = await client.put(f"{route}/{ids['ticket-desk']}", headers=bearer(owner), json={"allowed": True})
    assert loosen.status_code == 403 and loosen.json()["detail"]["code"] == "platform_admin_required"
    assert (await client.put(f"{route}/{ids['docs-search']}", headers=bearer(owner), json={"allowed": False})).status_code == 200
    own = await client.put(f"{route}/{ids['our-own']}", headers=bearer(owner), json={"allowed": True})
    assert own.status_code == 200, own.text
    outsider = await seed_member(db, workspace_id=other_id, role="owner")
    assert (await client.get(route, headers=bearer(outsider))).status_code in {403, 404}


@pytest.mark.asyncio
async def test_a_workspace_task_model_is_stored_and_wins_over_the_platform_task_model(client, db):
    from app.services.model_selection.gates import WorkspaceScope
    from app.services.model_selection.resolver import ModelRequest, resolve_model
    from app.services.model_selection.snapshot import load_scope
    from tests.test_model_selection_resolver import FAST, INTERNAL, LARGE, _snapshot

    admin = await make_user(db, admin=True)
    project = await _workspace(db, data_policy={"classification": "internal"})
    project_id = project.id
    route = BASE.format(project_id) + "/models"
    view = (await client.get(route, headers=bearer(admin))).json()
    assert {task["key"] for task in view["tasks"]} >= {"summarize", "memory"}
    unknown = await client.put(route, headers=bearer(admin),
                               json={**view["contract"], "task_overrides": {"summarize": "no-such-model"}})
    assert unknown.status_code == 422
    allowed = [row["key"] for row in view["models"] if row["allowed"] and "chat" in row["used_in"]]
    assert allowed, "the seeded platform order serves chat"
    saved = await client.put(route, headers=bearer(admin),
                             json={**view["contract"], "task_overrides": {"summarize": allowed[0]}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["contract"]["task_overrides"] == {"summarize": allowed[0]}
    scope = await load_scope(db, workspace_id=project_id)
    assert dict(scope.task_overrides) == {"summarize": allowed[0]}
    snapshot = _snapshot(FAST, LARGE, tasks={"summarize": "fast"})
    own = WorkspaceScope(data_class=INTERNAL.data_class, task_overrides=(("summarize", "large"),))
    assert resolve_model(snapshot, own, ModelRequest(task="summarize")).start == "large"
    assert resolve_model(snapshot, INTERNAL, ModelRequest(task="summarize")).start == "fast"


@pytest.mark.asyncio
async def test_an_owner_cannot_allow_seats_on_the_models_page(client, db):
    project = await _workspace(db, data_policy={"classification": "internal"})
    owner = await seed_member(db, workspace_id=project.id, role="owner")
    route = BASE.format(project.id) + "/models"
    contract = (await client.get(route, headers=bearer(owner))).json()["contract"]
    seat = {**contract["seat"], "mode": "allowed"}
    refused = await client.put(route, headers=bearer(owner), json={**contract, "seat": seat})
    # There is one seat editor, so the Models page never writes seat keys: a change is refused before any
    # role check and points at the seat-mode route, where an owner gets 403 platform_admin_required
    # (test_a_workspace_owner_may_only_tighten_the_seat_settings).
    assert refused.status_code == 422
    assert (refused.json()["detail"]["code"], refused.json()["detail"]["path"]) == ("seat_setting_via_seat_route",
                                                                                    "seat.mode")
    after = (await client.get(route, headers=bearer(owner))).json()["contract"]
    assert after["seat"]["mode"] == contract["seat"]["mode"] != "allowed"


@pytest.mark.asyncio
async def test_the_tool_policy_the_dispatch_enforces_is_shown(client, db):
    admin = await make_user(db, admin=True)
    project = await _workspace(db, tool_policy={"denylist": ["shell_exec"]})
    view = (await client.get(BASE.format(project.id) + "/tools", headers=bearer(admin))).json()
    assert view["source"] == "tool_policy" and "shell_exec" in view["policy"]["denylist"]


def test_the_mcp_rule_uses_the_session_raised_level_and_the_instance_default():
    set_effect_rules((EffectRule("mcp_server", "ticket-desk", "restricted"),))
    try:
        config = {"data_policy": {"classification": "internal"}, "mcp_policy": {"enabled_servers": ["ticket-desk"]}}
        assert mcp_server_access_decision("ticket-desk", config).allowed
        raised = mcp_server_access_decision("ticket-desk", config, session_data_policy={"classification": "restricted"})
        assert raised.reason == "classification_mcp_server_off"
        from app.services.knowledge.projection import workspace_classification_default as defaults

        defaults._known_admin_default[:] = [("secret",)]
        unclassified = {"mcp_policy": {"enabled_servers": ["ticket-desk"]}}
        assert not mcp_server_access_decision("ticket-desk", unclassified).allowed, "no level: the Instance default"
    finally:
        set_effect_rules(())
        from app.services.knowledge.projection import workspace_classification_default as defaults

        defaults._known_admin_default.clear()


def test_a_workspace_cannot_exempt_a_tool_from_approval():
    set_platform_default({"require_for_risks": ["high"], "require_for_tools": ["send_email"], "exempt_tools": []})
    try:
        policy = effective_policy({"approval_policy": {"mode": "add", "require_for_tools": ["create_ticket"],
                                                       "exempt_tools": ["send_email", "create_ticket"]}})
        assert "exempt_tools" not in policy and set(policy["require_for_tools"]) == {"send_email", "create_ticket"}
    finally:
        set_platform_default({"require_for_risks": [], "require_for_tools": [], "exempt_tools": []})


@pytest.mark.asyncio
async def test_backup_history_names_deleted_users_and_workspaces_not_ids(db):
    from app.models import DataExportJob

    job_id = str(uuid.uuid4())
    db.add(DataExportJob(id=job_id, created_by=str(uuid.uuid4()), export_type="admin_config_backup", scope_type="project",
                         scope_id=str(uuid.uuid4()), format="json", status="failed", summary_json={}))
    await db.commit()
    row = next(entry for entry in await backup_history(db) if entry["id"] == job_id)
    assert row["workspace"] == DELETED_WORKSPACE and row["by"] == DELETED_USER
