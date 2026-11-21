"""The agent tool surface is persisted and survives every path that carries an agent.

Panel create/save/reload, unrelated saves, step edits, revision snapshot/publish/restore,
execution payloads, and export/import. Unknown values and No tools combined with tool-using
steps are refused before anything is stored.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import AgentDefinition, Project
from app.services.agent_definition_payload import payload_from_snapshot, serialize_agent_definition_payload
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revision_store import list_agent_definition_revisions
from app.services.agent_definition_revisions import create_draft_revision, restore_revision
from app.services.agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum
from app.services.agent_definition_validation import validate_definition_snapshot
from app.services.agent_tool_surface_decision import apply_tool_surface_decision_to_profile, evaluate_agent_tool_surface
from app.services.export_package.content import serialize_agent_content
from app.services.export_package.upsert import upsert_agent_from_package
from app.services.session.execution_gate import evaluate_execution_gate
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY
from tests.agent_definition_revision_fixtures import admin_user, make_definition

# --- present invalid values fail closed, a missing key stays governed (judge review) ----


def _gate_for_payload(payload: dict):
    decision = evaluate_agent_tool_surface(payload, workflow_tools_declared=False)
    profile = apply_tool_surface_decision_to_profile({"status": "allowed", "reason": "ok"}, decision)
    return evaluate_execution_gate(profile), profile


async def _definition_with_stored_surface(db, value: str) -> AgentDefinition:
    """A persisted row holding *value*, written past every validating writer (as a manual DB edit would)."""
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    await db.execute(update(AgentDefinition).where(AgentDefinition.id == definition.id).values(tool_surface=value))
    await db.flush()
    await db.refresh(definition, ["tool_surface", "steps", "group"])
    return definition


# --- revisions and execution payloads ------------------------------------------


@pytest.mark.asyncio
async def test_revisions_publish_and_restore_keep_no_tools(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    definition.tool_surface = "none"
    await db.flush()

    source = await create_draft_revision(db, definition=definition, created_by=admin.id)
    assert source.snapshot["definition"]["tool_surface"] == "none"
    await publish_revision(db, revision=source, published_by=admin.id)
    published_payload = payload_from_snapshot(
        source.snapshot["definition"], source.snapshot["steps"], definition_id=definition.id
    )
    assert published_payload["toolSurface"] == "none"

    definition.tool_surface = "governed"
    await db.flush()
    await restore_revision(db, revision=source, definition=definition, current_user=admin)
    assert definition.tool_surface == "none"

    loaded = (
        await db.execute(select(AgentDefinition).where(AgentDefinition.id == definition.id))
    ).scalar_one()
    await db.refresh(loaded, ["steps", "group"])
    assert serialize_agent_definition_payload(loaded)["toolSurface"] == "none"


@pytest.mark.asyncio
async def test_a_governed_snapshot_is_unchanged_by_the_new_field(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    revisions = await list_agent_definition_revisions(db, definition.id)
    snapshot = build_definition_snapshot(definition, [])
    assert "tool_surface" not in snapshot["definition"]
    assert compute_snapshot_checksum(snapshot) == compute_snapshot_checksum(build_definition_snapshot(definition, []))
    assert all("tool_surface" not in revision.snapshot["definition"] for revision in revisions)


@pytest.mark.asyncio
async def test_publication_refuses_unknown_and_conflicting_snapshots(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    source = await create_draft_revision(db, definition=definition, created_by=admin.id)

    conflicting = {**source.snapshot, "definition": {**source.snapshot["definition"], "tool_surface": "none"}}
    unknown = {**source.snapshot, "definition": {**source.snapshot["definition"], "tool_surface": "text"}}

    conflict_codes = [issue.code for issue in (await validate_definition_snapshot(db, conflicting)).issues]
    unknown_codes = [issue.code for issue in (await validate_definition_snapshot(db, unknown)).issues]
    assert conflict_codes == ["tool_surface_conflict"]
    assert unknown_codes == ["unknown_tool_surface"]
    assert (await validate_definition_snapshot(db, source.snapshot)).ok


# --- export / import ------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_and_import_keep_no_tools_and_refuse_bad_packages(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    definition.tool_surface = "none"
    await db.flush()
    loaded = (await db.execute(select(AgentDefinition).where(AgentDefinition.id == definition.id))).scalar_one()
    await db.refresh(loaded, ["steps"])
    entity = serialize_agent_content(loaded)["entity"]
    assert entity["tool_surface"] == "none"

    target = Project(id=str(uuid.uuid4()), name=f"import-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(target)
    await db.flush()
    imported, _warnings = await upsert_agent_from_package(
        db, current_user=admin, entity=entity, overwrite_existing=False, name_override="Imported package"
    )
    assert imported.tool_surface == "none"

    legacy = {key: value for key, value in entity.items() if key != "tool_surface"}
    legacy_import, _ = await upsert_agent_from_package(
        db, current_user=admin, entity=legacy, overwrite_existing=False, name_override="Legacy package"
    )
    assert legacy_import.tool_surface == "governed"

    bad_value = {**entity, "tool_surface": "text"}
    conflicting = {**entity, "steps": [{"name": "Search", "allowed_tools": ["web_search"], "is_enabled": True}]}
    for package, status in ((bad_value, 422), (conflicting, 409)):
        with pytest.raises(HTTPException) as refused:
            await upsert_agent_from_package(
                db, current_user=admin, entity=package, overwrite_existing=False,
                name_override=f"Refused {status}"
            )
        assert refused.value.status_code == status


@pytest.mark.parametrize("present", ["", None, "text"])
def test_a_snapshot_with_a_present_invalid_value_reaches_the_gate_blocked(present):
    payload = payload_from_snapshot({"name": "a", "tool_surface": present}, [], definition_id="d1")
    assert payload["toolSurface"] == present
    gate, profile = _gate_for_payload(payload)
    assert (gate.allowed, gate.status, profile["reason_code"]) == (False, "needs_configuration", "agent_tool_surface_invalid")


def test_a_legacy_snapshot_without_the_key_stays_governed():
    payload = payload_from_snapshot({"name": "a"}, [], definition_id="d1")
    assert payload["toolSurface"] == "governed"
    gate, profile = _gate_for_payload(payload)
    assert gate.allowed and "agent_tool_surface" not in (profile.get("requirements") or {})


@pytest.mark.asyncio
async def test_a_persisted_empty_value_fails_closed_in_payload_snapshot_and_validation(db):
    definition = await _definition_with_stored_surface(db, "")

    payload = serialize_agent_definition_payload(definition)
    assert payload["toolSurface"] == ""
    gate, _profile = _gate_for_payload(payload)
    assert gate.allowed is False

    snapshot = build_definition_snapshot(definition, [])
    assert snapshot["definition"]["tool_surface"] == "", "the snapshot writer must not erase it into governed"
    codes = [issue.code for issue in (await validate_definition_snapshot(db, snapshot)).issues]
    assert codes == ["unknown_tool_surface"]
    assert serialize_agent_content(definition)["entity"]["tool_surface"] == ""


@pytest.mark.asyncio
async def test_restore_refuses_a_published_snapshot_with_a_present_invalid_value(db):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=0)
    definition.tool_surface = "none"
    await db.flush()
    revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
    # A published row whose snapshot carries an empty value (written past publication validation).
    revision.snapshot = {**revision.snapshot, "definition": {**revision.snapshot["definition"], "tool_surface": ""}}
    revision.status = "published"
    await db.flush()

    with pytest.raises(HTTPException) as refused:
        await restore_revision(db, revision=revision, definition=definition, current_user=admin)

    assert refused.value.status_code == 422
    assert definition.tool_surface == "none"


@pytest.mark.asyncio
async def test_import_refuses_an_explicit_null_before_overwriting_a_text_only_agent(db):
    admin = await admin_user(db)
    target = Project(id=str(uuid.uuid4()), name=f"null-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(target)
    await db.flush()
    existing = await make_definition(db, owner=admin, project_id=None, steps=0, name="Text only target")
    existing.tool_surface = "none"
    await db.flush()
    entity = {"name": "Text only target", "goal": "Overwritten goal", "tool_surface": None, "steps": []}

    with pytest.raises(HTTPException) as refused:
        await upsert_agent_from_package(
            db, current_user=admin, entity=entity, overwrite_existing=True, name_override=None
        )

    assert refused.value.status_code == 422
    await db.refresh(existing, ["tool_surface", "goal"])
    assert (existing.tool_surface, existing.goal) == ("none", "Prove the revision contract")


@pytest.mark.asyncio
async def test_an_admin_tool_clone_keeps_no_tools(db):
    admin = await admin_user(db)
    source = await make_definition(db, owner=admin, steps=0, name=f"Clone source {uuid.uuid4().hex[:6]}")
    source.tool_surface = "none"
    await db.commit()
    context = ToolContext(
        user_id=admin.id, project_ids=[], roles=["admin"], session_id="session", project_config={}, db=db,
        workspace_root=str(Path.cwd()),
    )

    result = await TOOL_REGISTRY["admin_create_agent"].execute(
        {"name": f"Clone {uuid.uuid4().hex[:6]}", "clone_from_agent_id": source.id}, context
    )

    assert result["status"] == "created", result
    assert (await db.get(AgentDefinition, result["agent"]["id"])).tool_surface == "none"
