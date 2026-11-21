"""Closed authored schema; legacy lists and caller authority fields never become typed offers."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.workflow_runs.handoff.contract import canonical_hash, validate_action, validate_contract


def contract():
    return {"schema_version": "handoff/v1", "owner": f"person:{uuid4()}",
        "artefacts": ["definition_of_ready"], "acceptance": "Inspect the confirmed task",
        "scope": {"workspace_id": str(uuid4()), "work_item_id": None, "repository": None,
                  "service_ids": [], "connection_ids": [], "source_ids": []},
        "detach": False, "timeout_seconds": 300, "deputy": None}


@pytest.mark.parametrize("change", [
    lambda c: c.update(schema_version="handoff/v2"), lambda c: c.update(owner="requester"),
    lambda c: c.update(owner="role:administrator"), lambda c: c.update(detach=1),
    lambda c: c.update(timeout_seconds=True), lambda c: c.update(timeout_seconds=0),
    lambda c: c.update(artefacts=["unknown"]),
    lambda c: c.update(artefacts=["definition_of_ready", "definition_of_ready"]),
    lambda c: c.update(acceptance=" "), lambda c: c.update(deputy=f"person:{uuid4()}"),
    lambda c: c.update(sender_token="secret"), lambda c: c["scope"].update(extra="admin"),
    lambda c: c["scope"].pop("connection_ids"),
])
def test_closed_contract_refuses_ambiguous_authority(change):
    value = contract()
    change(value)
    with pytest.raises(HTTPException) as refused:
        validate_contract(value)
    assert refused.value.status_code == 422


def test_schema_is_copied_and_legacy_list_is_not_a_typed_handoff():
    raw = contract()
    value = validate_contract(raw)
    raw["scope"]["connection_ids"].append(str(uuid4()))
    assert value["scope"]["connection_ids"] == []
    with pytest.raises(HTTPException):
        validate_contract(["definition_of_ready"])


@pytest.mark.parametrize("owner", ["role:doc_owner", "person:", "group:"])
def test_known_owner_discriminators(owner):
    raw = contract()
    raw["owner"] = owner + str(uuid4()) if owner.endswith(":") else owner
    assert validate_contract(raw)["owner"] == raw["owner"]


@pytest.mark.parametrize("mutation", [
    {"actor_id": str(uuid4())}, {"round": True}, {"runtime_target": {"kind": "server", "token": "secret"}},
    {"runtime_target": {"kind": "server", "user_id": str(uuid4())}}, {"runtime_target": {"kind": "unknown"}},
    {"payload_hash": "sha256:wrong"}, {"expected_state_version": 0},
])
def test_accept_cannot_supply_actor_or_unknown_runtime_authority(mutation):
    value = {"action": "accept", "payload_hash": canonical_hash({}), "round": 1,
             "expected_state_version": 1, "runtime_target": {"kind": "server"}, **mutation}
    with pytest.raises(HTTPException):
        validate_action(value)


def test_decline_requires_reason_and_cannot_choose_runtime():
    value = {"action": "decline", "payload_hash": canonical_hash({}), "round": 1,
             "expected_state_version": 1, "reason": "Unavailable this round"}
    assert validate_action(value) == value
    for invalid in ({**value, "reason": ""}, {**value, "runtime_target": {"kind": "server"}}):
        with pytest.raises(HTTPException):
            validate_action(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [None, "device_id", "folder", "model", "profile"])
async def test_admitted_device_defaults_cannot_replace_explicit_target_fields(drift):
    from types import SimpleNamespace

    from app.services.workflow_runs.handoff.rules import _rights

    actor = SimpleNamespace(id=str(uuid4()))
    row = SimpleNamespace(contract=contract(), envelopes={})
    selected = {"kind": "device", "device_id": str(uuid4()), "folder": "/tmp/controlled", "model": "named-model"}
    if drift == "profile":
        selected["profile"] = "explicit"
    effective = {**selected, "profile": selected.get("profile", "governed")}
    if drift:
        effective[drift] = str(uuid4()) if drift == "device_id" else "changed"
    async def admitted(**kwargs):
        return {"allowed": True, "actor_id": actor.id,
            "scope_digest": canonical_hash({"scope": row.contract["scope"], "envelopes": {}}),
            "runtime_target": effective}
    if drift:
        with pytest.raises(HTTPException):
            await _rights(None, row, actor, selected, admitted)
    else:
        proof = await _rights(None, row, actor, selected, admitted)
        assert proof["runtime_target"] == {**selected, "profile": "governed"}
