from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_payload import payload_from_snapshot, serialize_agent_definition_payload
from app.services.agent_definition_revision_store import load_definition_steps
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_definition_snapshot import build_definition_snapshot
from app.services.agent_definition_types import AgentPayload, DefinitionSnapshot
from tests.agent_definition_revision_fixtures import admin_user, make_definition
from tests.typed_dict_support import shape_problems


async def _definitions(db: AsyncSession):
    admin = await admin_user(db)
    plain = await make_definition(db, owner=admin, name="Plain agent")
    configured = await make_definition(db, owner=admin, name="Configured agent", steps=1)
    configured.tool_surface = "none"
    configured.reply_contract_json = json.dumps({"kind": "json_object", "schema": {
        "type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}})
    configured.capability_ceiling = "write"
    configured.default_workflow_key = "triage"
    configured.execution_mode = "coding_delivery"
    configured.runtime_preference = "device"
    configured.chat_selectable = True
    configured.tools_deny_json = json.dumps(["shell"])
    await db.flush()
    return admin, [plain, configured]


async def test_a_definition_snapshot_and_both_payloads_conform(db: AsyncSession):
    admin, definitions = await _definitions(db)
    for definition in definitions:
        steps = await load_definition_steps(db, definition.id)
        snapshot = build_definition_snapshot(definition, steps)
        assert shape_problems(snapshot, DefinitionSnapshot, "snapshot") == []
        revision = await create_draft_revision(db, definition=definition, created_by=admin.id)
        assert shape_problems(revision.snapshot, DefinitionSnapshot, "stored") == []
        await db.refresh(definition, attribute_names=["steps", "group"])
        assert shape_problems(serialize_agent_definition_payload(definition), AgentPayload, "live") == []
        pinned = payload_from_snapshot(revision.snapshot["definition"], revision.snapshot["steps"],
                                       definition_id=definition.id, live_step_ids_by_position={1: "step-1"})
        assert shape_problems(pinned, AgentPayload, "pinned") == []
