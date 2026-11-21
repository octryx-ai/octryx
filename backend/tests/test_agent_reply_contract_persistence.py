"""Contract: the reply contract is persisted and carried like the tool surface.

Panel create/save/reload in both spellings; an omitted update keeps it, ``{"kind": "text"}`` turns
it off, ``null``/unknown/conflicting/oversized values are refused with nothing stored; a corrupt
stored value fails closed (payload verbatim, validation, refused unrelated save). Revisions pin
the contract (published execution reads the pinned one, not the draft), text snapshots keep their
checksums, and export/import round-trip it while legacy packages stay text.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import AgentDefinition, Project
from app.services.agent_definition_payload import payload_from_snapshot, serialize_agent_definition_payload
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision, restore_revision
from app.services.agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum
from app.services.agent_definition_validation import validate_definition_snapshot
from app.services.export_package.content import serialize_agent_content
from app.services.export_package.upsert import upsert_agent_from_package
from tests.agent_definition_revision_fixtures import admin_user, make_definition
from tests.conftest import ADMIN_PASSWORD

_AGENTS = "/admin/chat/api/panel/agents"
TEXT = {"kind": "text"}
CHECKED = {"kind": "json_object",
           "schema": {"type": "object", "properties": {"sum": {"type": "integer"}}, "required": ["sum"]}}
OTHER = {"kind": "json_object",
         "schema": {"type": "object", "properties": {"total": {"type": "number"}}, "required": []}}


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _create(client, **fields) -> dict:
    body = {"name": f"Reply {uuid.uuid4().hex[:6]}", "agent_type": "diagnosis", "thinking_level": "light", **fields}
    response = await client.post(_AGENTS, json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _reload(client, agent_id: str) -> dict:
    response = await client.get(_AGENTS)
    assert response.status_code == 200
    return next(agent for agent in response.json() if agent["id"] == agent_id)


async def test_panel_create_update_and_reload_keep_omit_and_disable(client):
    await _login(client)
    legacy = await _create(client)
    checked = await _create(client, reply_contract=CHECKED)
    assert legacy["replyContract"] == TEXT
    assert (await _reload(client, checked["id"]))["replyContract"] == CHECKED

    url = f"{_AGENTS}/{checked['id']}"
    assert (await client.put(url, json={"name": "Renamed", "goal": "New"})).status_code == 200
    assert (await _reload(client, checked["id"]))["replyContract"] == CHECKED, "omitted update keeps it"
    assert (await client.put(url, json={"name": "Renamed", "reply_contract": OTHER})).status_code == 200
    assert (await _reload(client, checked["id"]))["replyContract"] == OTHER
    assert (await client.put(url, json={"name": "Renamed", "reply_contract": TEXT})).status_code == 200
    assert (await _reload(client, checked["id"]))["replyContract"] == TEXT, "explicit text turns the check off"
    stored = await client.get(_AGENTS)
    assert stored.status_code == 200


@pytest.mark.parametrize("body", [
    {"reply_contract": None},
    {"reply_contract": "json"},
    {"reply_contract": {"kind": "json_object"}},
    {"reply_contract": {**CHECKED, "schema": {**CHECKED["schema"], "properties": {"sum": {"type": "object"}}}}},
    {"reply_contract": {**CHECKED, "schema": {**CHECKED["schema"], "required": ["sum", "sum"]}}},
    {"reply_contract": {**CHECKED, "schema": {**CHECKED["schema"], "x": "y" * 17000}}},
])
async def test_panel_refuses_invalid_values_without_storing_anything(client, body):
    await _login(client)
    agent = await _create(client, reply_contract=CHECKED)
    refused = await client.put(f"{_AGENTS}/{agent['id']}", json={"name": "Not applied", **body})
    assert refused.status_code == 422
    # The shared 422 handler echoes request input for every field; the messages themselves never do.
    errors = refused.json()["validation_errors"]
    assert all("y" * 50 not in str(error.get("msg", "")) for error in errors)
    created = await client.post(_AGENTS, json={"name": "Bad create", **body})
    assert created.status_code == 422
    reloaded = await _reload(client, agent["id"])
    assert (reloaded["replyContract"], reloaded["name"]) == (CHECKED, agent["name"])


async def test_a_corrupt_stored_contract_fails_closed_and_an_unrelated_save_is_refused(client, db):
    await _login(client)
    agent = await _create(client, reply_contract=CHECKED)
    await db.execute(update(AgentDefinition).where(AgentDefinition.id == agent["id"]).values(
        reply_contract_json='{"kind": "json_object"}'))
    await db.commit()
    assert (await _reload(client, agent["id"]))["replyContract"] == {"kind": "json_object"}, "verbatim, never text"
    refused = await client.put(f"{_AGENTS}/{agent['id']}", json={"name": "Renamed"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "agent_reply_contract_invalid"
    fixed = await client.put(f"{_AGENTS}/{agent['id']}", json={"name": "Renamed", "reply_contract": TEXT})
    assert fixed.status_code == 200 and fixed.json()["replyContract"] == TEXT


async def test_unreadable_stored_text_reaches_validation_as_invalid(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await db.execute(update(AgentDefinition).where(AgentDefinition.id == definition.id).values(
        reply_contract_json="{not json"))
    await db.flush()
    await db.refresh(definition, ["reply_contract_json", "steps", "group"])
    assert serialize_agent_definition_payload(definition)["replyContract"] == "{not json"
    snapshot = build_definition_snapshot(definition, [])
    codes = [issue.code for issue in (await validate_definition_snapshot(db, snapshot)).issues]
    assert codes == ["invalid_reply_contract"]


# --- revisions -----------------------------------------------------------------------------------------


async def test_published_execution_uses_the_pinned_contract_and_restore_brings_it_back(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    definition.reply_contract_json = '{"kind":"json_object","schema":{"type":"object","properties":{"sum":{"type":"integer"}},"required":["sum"]}}'
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    assert revision.snapshot["definition"]["reply_contract"] == CHECKED
    await publish_revision(db, revision=revision, published_by=admin.id)

    definition.reply_contract_json = None  # the live draft moves on to free text
    await db.flush()
    pinned = payload_from_snapshot(revision.snapshot["definition"], revision.snapshot["steps"], definition_id=definition.id)
    loaded = (await db.execute(select(AgentDefinition).where(AgentDefinition.id == definition.id))).scalar_one()
    await db.refresh(loaded, ["steps", "group"])
    assert pinned["replyContract"] == CHECKED and serialize_agent_definition_payload(loaded)["replyContract"] == TEXT

    await restore_revision(db, revision=revision, definition=definition, current_user=admin)
    assert serialize_agent_definition_payload(definition)["replyContract"] == CHECKED


async def test_text_snapshots_keep_their_checksum_and_legacy_payloads_are_text(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    snapshot = build_definition_snapshot(definition, [])
    assert "reply_contract" not in snapshot["definition"]
    without_column = {**snapshot, "definition": dict(snapshot["definition"])}
    assert compute_snapshot_checksum(snapshot) == compute_snapshot_checksum(without_column)
    assert payload_from_snapshot({"name": "legacy"}, [], definition_id="d1")["replyContract"] == TEXT


async def test_publication_refuses_present_invalid_contracts(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    for present in (None, {"kind": "json_object"}, "text"):
        bad = {**source.snapshot, "definition": {**source.snapshot["definition"], "reply_contract": present}}
        assert [issue.code for issue in (await validate_definition_snapshot(db, bad)).issues] == ["invalid_reply_contract"]
    good = {**source.snapshot, "definition": {**source.snapshot["definition"], "reply_contract": CHECKED}}
    assert (await validate_definition_snapshot(db, good)).ok


# --- export / import -----------------------------------------------------------------------------------


async def test_export_import_round_trip_legacy_text_and_refusals(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await db.refresh(definition, ["steps", "group"])
    plain = serialize_agent_content(definition)["entity"]
    assert "reply_contract" not in plain, "ordinary exports keep their old content"
    definition.reply_contract_json = '{"kind":"json_object","schema":{"type":"object","properties":{"sum":{"type":"integer"}},"required":["sum"]}}'
    await db.flush()
    entity = serialize_agent_content(definition)["entity"]
    assert entity["reply_contract"] == CHECKED

    target = Project(id=str(uuid.uuid4()), name=f"import-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(target)
    await db.flush()
    imported, _ = await upsert_agent_from_package(
        db, current_user=admin, entity=entity, overwrite_existing=False, name_override="Imported")
    await db.refresh(imported, ["steps", "group"])
    assert serialize_agent_definition_payload(imported)["replyContract"] == CHECKED
    legacy, _ = await upsert_agent_from_package(
        db, current_user=admin, entity=plain, overwrite_existing=False, name_override="Legacy")
    assert legacy.reply_contract_json is None

    for bad in (None, {"kind": "json_object"}):
        with pytest.raises(HTTPException) as refused:
            await upsert_agent_from_package(
                db, current_user=admin, entity={**entity, "reply_contract": bad}, overwrite_existing=True,
                name_override="Imported")
        assert refused.value.status_code == 422
    await db.refresh(imported, ["reply_contract_json", "steps", "group"])
    assert serialize_agent_definition_payload(imported)["replyContract"] == CHECKED, "a refused import writes nothing"
