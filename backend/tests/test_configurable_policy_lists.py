"""Code-owned policy lists are admin data with a code seed, closed validation, versions and audit."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.services.session.turn_runtime_selection as selection_module
from app.models import AuditLog, ControlPlaneRuntimeTarget, User
from app.services.governed_default_tool_sets import GOVERNED_DEFAULT_TOOL_SETS, governed_default_tool_set
from app.services.model_family_policy import WEAK_CODING_MODEL_FAMILIES
from app.services.model_selection.gates import CatalogModel, WorkspaceScope
from app.services.model_selection.snapshot import SelectionSnapshot
from app.services.policy_lists.admin import reset_policy_list, save_policy_list
from app.services.policy_lists.errors import PolicyListError
from app.services.policy_lists.live import seed_policy_lists
from app.services.session.turn_runtime_requirement import UnsupportedModelCapabilityError, required_model_capability
from app.services.session.turn_runtime_selection import RuntimeChoice, RuntimeSelectionSource, resolve_turn_runtime
from app.services.workflow_runs.phase_validation import validate_phase_payload
from tests.conftest import ADMIN_PASSWORD

NOVA = "amazon.nova-2-lite-v1:0"
CODING = {"workflow_id": "coding_change_tdd", "required_model_capability": "coding"}
SETS = "/admin/chat/api/panel/default-tool-sets"
LISTS = "/admin/chat/api/panel/policy-lists"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _login(client) -> None:
    assert (await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})).status_code == 303


async def _audit(db, list_id: str) -> list[tuple[str, str]]:
    rows = (await db.execute(select(AuditLog).where(AuditLog.resource_id == list_id))).scalars()
    return sorted((row.action, row.details["key"]) for row in rows)


async def _refused(operation) -> PolicyListError:
    with pytest.raises(PolicyListError) as refused:
        await operation
    return refused.value


def _target(target_id: str, model_id: str, priority: int, tags: tuple[str, ...] = ()):
    return SimpleNamespace(
        id=target_id, model_id=model_id, priority=priority, is_active=True, use_case_tags=[], capability_tags=list(tags)
    )


async def _runtime_for_coding(monkeypatch, targets, coding: set[str]) -> str:
    async def fake_targets(_db, *args, **kwargs):
        return targets

    models = {
        target.id: CatalogModel(
            key=target.id, provider_id="p", model_id=target.model_id, display_name=target.id, provider_name="P",
            driver="bedrock_api", enabled=True, provider_active=True, cleared_up_to="internal",
            capabilities={"tools": True, "vision": False, "coding": target.id in coding, "long_context": False},
            target_ids=(target.id,),
        )
        for target in targets
    }
    snapshot = SelectionSnapshot(models=models, by_target={t.id: t.id for t in targets},
                                 order=tuple(t.id for t in sorted(targets, key=lambda t: t.priority)))

    async def fake_selection(_db, _view, _session):
        return snapshot, WorkspaceScope()

    monkeypatch.setattr(selection_module, "get_runtime_targets", fake_targets)
    monkeypatch.setattr(selection_module, "load_turn_selection", fake_selection)
    labels = {"": "Auto", **{target.id: target.id for target in targets}}
    choice = RuntimeChoice("", "", labels, RuntimeSelectionSource.GLOBAL_DEFAULT)
    await resolve_turn_runtime(
        None,
        choice,
        runtime_target_id_explicit=False,
        session=None,
        workspace_execution_view=None,
        agent_runtime_target_id=None,
        workflow_contract=CODING,
    )
    return choice.runtime_target_id


def test_the_seeds_are_the_current_behaviour():
    live = seed_policy_lists()

    for capability_type, seed in GOVERNED_DEFAULT_TOOL_SETS.items():
        assert live.default_tool_sets[capability_type].key == f"{capability_type}.v{seed.version}"
        assert live.default_tool_sets[capability_type].tools == seed.tools
    assert live.weak_coding_model_families == WEAK_CODING_MODEL_FAMILIES
    assert dict(live.model_capabilities) == {"coding": "Coding"}




@pytest.mark.asyncio
async def test_an_edited_weak_family_list_no_longer_changes_the_runtime_selection(db, monkeypatch):
    # The list only seeds the coding checkbox of a new catalog row; the
    # selection reads the checkbox. Editing the list keeps its versioning, validation and audit.
    admin = await _admin(db)
    targets = [_target("nova", NOVA, 1), _target("sonnet", "anthropic.claude-sonnet-4-5", 2)]
    assert await _runtime_for_coding(monkeypatch, targets, {"sonnet"}) == "sonnet"

    edited = [family for family in WEAK_CODING_MODEL_FAMILIES if family != "nova-2-lite"]
    saved = await save_policy_list(db, "weak_coding_model_families", edited, actor_id=admin.id, expected_version=1)

    assert saved["key"] == "weak_coding_model_families.v2"
    assert await _runtime_for_coding(monkeypatch, targets, {"sonnet"}) == "sonnet"
    invalid = await _refused(save_policy_list(db, "weak_coding_model_families", ["a"], actor_id=admin.id, expected_version=None))
    assert invalid.code == "invalid_entry"
    duplicate = await _refused(
        save_policy_list(db, "weak_coding_model_families", ["gemma", "Gemma"], actor_id=admin.id, expected_version=None)
    )
    assert duplicate.code == "duplicate_entry"

    await reset_policy_list(db, "weak_coding_model_families", actor_id=admin.id)
    assert [action for action, _key in await _audit(db, "weak_coding_model_families")] == [
        "policy_list.reset",
        "policy_list.updated",
    ]


@pytest.mark.asyncio
async def test_the_catalog_coding_checkbox_decides_the_coding_requirement(monkeypatch):
    # The name says nothing: a "weak" name with the checkbox meets coding, a strong name without it does not.
    targets = [
        _target("opus", "anthropic.claude-opus-4", 1),
        _target("haiku", "claude-haiku-4.5", 2),
        _target("nova", NOVA, 3),
    ]
    assert await _runtime_for_coding(monkeypatch, targets, {"nova"}) == "nova"
    assert await _runtime_for_coding(monkeypatch, targets, {"haiku", "nova"}) == "haiku"


@pytest.mark.asyncio
async def test_the_capability_catalog_is_validated_for_targets_and_definitions(client, db):
    await _login(client)
    two = [{"key": "coding", "label": "Coding"}, {"key": "vision", "label": "Vision"}]

    saved = await client.put(f"{LISTS}/model_capabilities", json={"values": two})
    assert saved.status_code == 200 and saved.json()["key"] == "model_capabilities.v2"
    pinned = (await client.put(f"{LISTS}/model_capabilities", json={"values": two[1:]})).json()["detail"]
    assert pinned["code"] == "capability_in_use" and pinned["values"] == ["coding"]

    target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    unknown = await client.put(f"/admin/chat/api/panel/runtimes/{target.id}", json={"capability_tags": ["telepathy"]})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "unknown_capability"
    tagged = await client.put(f"/admin/chat/api/panel/runtimes/{target.id}", json={"capability_tags": ["vision"]})
    assert tagged.status_code == 200 and tagged.json()["capability_tags"] == ["vision"]
    carried = (await client.put(f"{LISTS}/model_capabilities", json={"values": two[:1]})).json()["detail"]
    assert carried["code"] == "capability_in_use" and carried["values"] == ["vision"]

    def definition(capability: str) -> dict:
        contract = {"workflow_id": "w", "when_to_use": "x", "required_model_capability": capability}
        return {"workflow_id": "w", "workflow_class": "w", "workflow_contract": contract}

    codes = {error["code"] for error in validate_phase_payload(definition("telepathy"))["errors"]}
    assert "unknown_capability" in codes
    codes = {error["code"] for error in validate_phase_payload(definition("vision"))["errors"]}
    assert "unknown_capability" not in codes
    with pytest.raises(UnsupportedModelCapabilityError):
        required_model_capability({"required_model_capability": "telepathy"})
    assert (await client.put(f"{LISTS}/no_such_list", json={"values": []})).status_code == 404


@pytest.mark.asyncio
async def test_a_default_set_edit_is_validated_versioned_and_audited(client, db):
    await _login(client)
    seed = next(entry for entry in (await client.get(SETS)).json()["sets"] if entry["capability_type"] == "diagnosis")
    edited = [family for family in seed["families"] if family["name"] != "web"]
    version = seed["version"]

    saved = await client.put(f"{SETS}/diagnosis", json={"families": edited, "expected_version": version})
    assert saved.status_code == 200 and saved.json()["key"] == f"diagnosis.v{version + 1}"
    assert governed_default_tool_set("diagnosis").key == f"diagnosis.v{version + 1}"

    stale = await client.put(f"{SETS}/diagnosis", json={"families": edited, "expected_version": version})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"
    unknown = [*edited, {"name": "extra", "tools": ["no_such_tool"]}]
    refused = (await client.put(f"{SETS}/diagnosis", json={"families": unknown})).json()["detail"]
    assert refused["code"] == "unknown_tool" and refused["values"] == ["no_such_tool"]
    without_selection = [family for family in edited if family["name"] != "workflow_selection"]
    refused = (await client.put(f"{SETS}/diagnosis", json={"families": without_selection})).json()["detail"]
    assert refused["code"] == "required_tool_missing"

    reset = await client.post(f"{SETS}/diagnosis/reset")
    assert reset.status_code == 200 and reset.json()["key"] == f"diagnosis.v{version + 2}" and reset.json()["matches_seed"]
    assert governed_default_tool_set("diagnosis").tools == GOVERNED_DEFAULT_TOOL_SETS["diagnosis"].tools
    assert await _audit(db, "default_tool_set.diagnosis") == [
        ("policy_list.reset", f"diagnosis.v{version + 2}"),
        ("policy_list.updated", f"diagnosis.v{version + 1}"),
    ]
