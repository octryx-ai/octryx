"""Workspace → Models — one list by display name, the existing stores
derived from it in one transaction, clearance enforced, the seat card's company models in /model."""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import select

from app.models import ControlPlaneConfig, ControlPlaneRuntimeTarget, Project, WorkspacePolicy
from app.models.project.workspace_composition import WorkspaceCapabilityBinding
from tests.model_gateway.conftest import gateway_config, gateway_provider
from tests.policy_engine_support import bearer, make_user

ROUTE = "/api/v1/admin/workspaces/{}/models"
GATEWAY_KEYS = {"octryx-general", "octryx-secure"}  # the seeded platform order adds direct models, which model_policy never gates


async def _setup(db, level: str = "internal", model_policy: dict | None = None) -> tuple[Project, str]:
    config = gateway_config()
    aliases = config["litellm_gateway"]["aliases"]
    aliases["octryx-general"]["display_name"] = "General model"
    aliases["octryx-secure"] = {**copy.deepcopy(aliases["octryx-general"]), "display_name": "Secure model",
                            "data_policy_class": "confidential"}
    provider = gateway_provider(config_json=config, display_name="Company gateway")
    db.add(provider)
    await db.flush()
    control = (await db.execute(select(ControlPlaneConfig))).scalars().first()
    target = ControlPlaneRuntimeTarget(id=str(uuid.uuid4()), config_id=control.id, provider_id=provider.id,
                                       model_id="octryx-general", priority=5, is_active=True)
    db.add(target)
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True,
                      config={"data_policy": {"classification": level},
                              **({"model_policy": model_policy} if model_policy is not None else {})})
    db.add(project)
    await db.commit()
    return project, target.id


@pytest.mark.asyncio
async def test_the_list_derives_bindings_default_model_policy_and_seat(client, db):
    admin = await make_user(db, admin=True)
    project, target_id = await _setup(db, "internal")
    view = (await client.get(ROUTE.format(project.id), headers=bearer(admin))).json()
    rows = {row["key"]: row for row in view["models"]}
    assert rows["octryx-general"]["label"] == "General model" and rows["octryx-general"]["used_in"] == ["chat", "coding_tools",
                                                                                              "device_runs"]
    assert rows["octryx-secure"]["used_in"] == ["coding_tools", "device_runs"], "an alias without a target"
    # No saved ``model_policy``: every admitted alias is allowed (``effective_model_policy``), and the page says so.
    assert view["contract"]["mode"] == "all_cleared"
    assert rows["octryx-general"]["allowed"] and rows["octryx-secure"]["allowed"]
    assert not any("runtime-target:" in str(row) for row in view["models"]), "never a raw binding key"

    # Every seat key is read-only here (their editor is the seat route): the stored values may be repeated.
    seat = dict(view["contract"]["seat"])
    body = {"mode": "selected", "selected": ["octryx-general", "octryx-secure"], "default": "octryx-general", "task_overrides": {},
            "seat": seat}
    saved = await client.put(ROUTE.format(project.id), json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    assert saved.json()["contract"]["selected"] == ["octryx-general", "octryx-secure"]
    assert saved.json()["contract"]["default"] == "octryx-general"

    await db.refresh(project)
    assert project.config["model_policy"]["allowed_aliases"] == ["octryx-general", "octryx-secure"]
    assert project.config["model_policy"]["allow_all_admitted_aliases"] is False
    gateway = project.config.get("agent_gateway_policy") or {}
    assert "seat_mode" not in gateway and "seat_allows_governed_models" not in gateway and "seat_models" not in gateway, \
        "no seat key is written by the models contract"
    policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project.id))).scalar_one()
    assert policy.runtime_policy["runtime_assignment_mode"] == "selected_only"
    assert "fallback_runtime_binding_key" not in policy.runtime_policy
    assert policy.default_bindings["runtime"] == f"runtime-target:{target_id}"
    bindings = (await db.execute(select(WorkspaceCapabilityBinding).where(
        WorkspaceCapabilityBinding.workspace_id == project.id, WorkspaceCapabilityBinding.capability_kind == "runtime"))
    ).scalars().all()
    enabled = {binding.source_entity_id for binding in bindings if binding.is_enabled}
    assert enabled == {target_id}, "only the selected chat model is enabled"

    everything = await client.put(ROUTE.format(project.id), headers=bearer(admin),
                                  json={**body, "mode": "all_cleared", "selected": [], "default": None})
    assert everything.status_code == 200
    await db.refresh(project)
    assert project.config["model_policy"]["allow_all_admitted_aliases"] is True


@pytest.mark.asyncio
async def test_a_model_above_the_level_and_a_default_outside_the_list_are_refused(client, db):
    admin = await make_user(db, admin=True)
    project, _target = await _setup(db, "confidential")
    route = ROUTE.format(project.id)  # read once: a refused write rolls the shared session back
    view = (await client.get(route, headers=bearer(admin))).json()
    general = next(row for row in view["models"] if row["key"] == "octryx-general")
    assert general["cleared"] is False and general["reason"] == "cleared only up to Internal"
    seat = {"mode": "forbidden", "subscription_models": [], "company_models_in_seat": False}
    refused = await client.put(route, headers=bearer(admin),
                               json={"mode": "selected", "selected": ["octryx-general"], "default": None, "seat": seat})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "workspace_model_not_cleared"
    only_alias = await client.put(route, headers=bearer(admin),
                                  json={"mode": "selected", "selected": ["octryx-secure"], "default": None, "seat": seat})
    assert only_alias.json()["detail"]["code"] == "workspace_models_empty", "chat needs a model"
    member = await make_user(db, admin=False)
    assert (await client.get(route, headers=bearer(member))).status_code == 404


SEAT = {"mode": "forbidden"}


@pytest.mark.asyncio
async def test_a_restrictive_model_policy_shows_as_selected_with_exactly_the_granted_aliases(client, db):
    # The runtime bindings may say "all installed" while model_policy grants one alias; the page must not show every
    # cleared model as allowed when the gateway refuses the others with model_alias_not_granted_for_project.
    admin = await make_user(db, admin=True)
    project, _target = await _setup(db, "internal", model_policy={"allowed_aliases": ["octryx-secure"]})
    view = (await client.get(ROUTE.format(project.id), headers=bearer(admin))).json()

    assert view["contract"]["mode"] == "selected" and GATEWAY_KEYS & set(view["contract"]["selected"]) == {"octryx-secure"}
    assert {row["key"]: row["allowed"] for row in view["models"] if row["key"] in GATEWAY_KEYS} == {
        "octryx-general": False, "octryx-secure": True}

    granted_all = {"allowed_aliases": [], "allow_all_admitted_aliases": True, "denied_aliases": ["octryx-secure"]}
    denied, _target = await _setup(db, "internal", model_policy=granted_all)
    view = (await client.get(ROUTE.format(denied.id), headers=bearer(admin))).json()
    assert view["contract"]["mode"] == "selected", "a denial wins over allow-all"
    assert GATEWAY_KEYS & set(view["contract"]["selected"]) == {"octryx-general"}


@pytest.mark.asyncio
async def test_a_save_round_trips_and_writes_model_policy_and_runtime_policy_from_one_contract(client, db):
    admin = await make_user(db, admin=True)
    policy = {"allowed_aliases": ["octryx-secure"], "denied_aliases": ["octryx-general", "elsewhere"]}
    project, target_id = await _setup(db, "internal", model_policy=policy)
    route = ROUTE.format(project.id)

    body = {"mode": "selected", "selected": ["octryx-general"], "default": "octryx-general", "task_overrides": {}, "seat": SEAT}
    saved = await client.put(route, json=body, headers=bearer(admin))
    assert saved.status_code == 200, saved.text
    assert saved.json()["contract"]["mode"] == "selected" and saved.json()["contract"]["selected"] == ["octryx-general"]
    assert (await client.get(route, headers=bearer(admin))).json()["contract"] == saved.json()["contract"]
    await db.refresh(project)
    assert project.config["model_policy"] == {"allowed_aliases": ["octryx-general"], "allow_all_admitted_aliases": False,
                                              "denied_aliases": ["elsewhere"]}, "the selected alias is no longer denied"
    workspace_policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project.id))
                        ).scalar_one()
    assert workspace_policy.runtime_policy["runtime_assignment_mode"] == "selected_only"
    assert workspace_policy.default_bindings["runtime"] == f"runtime-target:{target_id}"

    everything = await client.put(route, headers=bearer(admin),
                                  json={**body, "mode": "all_cleared", "selected": [], "default": None})
    assert everything.status_code == 200, everything.text
    assert everything.json()["contract"]["mode"] == "all_cleared"
    assert all(row["allowed"] for row in everything.json()["models"])
    await db.refresh(project)
    assert project.config["model_policy"]["allow_all_admitted_aliases"] is True
    assert project.config["model_policy"]["denied_aliases"] == ["elsewhere"]


@pytest.mark.asyncio
async def test_a_workspace_owner_cannot_select_a_model_the_policy_does_not_grant(client, db):
    from tests.knowledge_evidence_seed_support import seed_member

    project, _target = await _setup(db, "internal", model_policy={"allowed_aliases": ["octryx-secure"]})
    owner = await seed_member(db, workspace_id=project.id, role="owner")
    route = ROUTE.format(project.id)
    contract = (await client.get(route, headers=bearer(owner))).json()["contract"]

    widened = await client.put(route, headers=bearer(owner), json={**contract, "selected": ["octryx-general", "octryx-secure"]})
    assert widened.status_code == 403 and widened.json()["detail"]["path"] == "selected.octryx-general"


@pytest.mark.asyncio
@pytest.mark.parametrize(("seat", "path"), [
    ({"subscription_models": ["claude-sonnet-5"]}, "seat.subscription_models"),
    ({"company_models_in_seat": True}, "seat.company_models_in_seat"),
    ({"mode": "forbidden"}, "seat.mode"),  # the seat switch too
])
async def test_the_seat_model_keys_are_written_only_through_the_seat_route(client, db, seat, path):
    # One editor per key. The models contract reads the seat's model keys and refuses a
    # change with a code pointing to the seat route; nothing is written and no second audit row appears.
    from app.models import AuditLog

    admin = await make_user(db, admin=True)
    project, _target = await _setup(db, "internal")
    policy = {"seat_mode": "allowed", "seat_models": ["claude-opus-5-5"], "seat_allows_governed_models": False}
    project.config = {**project.config, "agent_gateway_policy": policy}
    await db.commit()
    project_id = project.id  # read once: a refused write rolls the shared session back
    route = ROUTE.format(project_id)
    stored = (await client.get(route, headers=bearer(admin))).json()["contract"]["seat"]
    assert stored == {"mode": "allowed", "subscription_models": ["claude-opus-5-5"], "company_models_in_seat": False}
    body = {"mode": "selected", "selected": ["octryx-general"], "default": "octryx-general", "task_overrides": {}}

    refused = await client.put(route, headers=bearer(admin), json={**body, "seat": {**stored, **seat}})

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert (detail["code"], detail["path"]) == ("seat_setting_via_seat_route", path)
    assert f"/api/v1/workspaces/{project_id}/agent-gateway/seat-mode" in detail["reason"]
    project = await db.get(Project, project_id)
    await db.refresh(project)
    assert project.config["agent_gateway_policy"] == policy
    audits = (await db.execute(select(AuditLog).where(AuditLog.resource_id == project_id))).scalars().all()
    assert not [row for row in audits if row.action == "admin.workspace.models_updated"]

    repeated = await client.put(route, headers=bearer(admin), json={**body, "seat": stored})
    without = await client.put(route, headers=bearer(admin), json=body)
    assert repeated.status_code == 200 and without.status_code == 200, without.text
    await db.refresh(project)
    assert project.config["agent_gateway_policy"] == policy, "the seat's model keys keep their stored values"
