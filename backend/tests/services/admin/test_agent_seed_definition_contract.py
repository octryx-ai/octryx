"""The shipped seed catalog is publishable, and stays that way."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition
from app.services.admin.governance.admin_agent_service import create_agent, update_agent
from app.services.agent_definition_revision_store import load_definition_steps
from app.services.agent_definition_snapshot import build_definition_snapshot
from app.services.agent_definition_validation import (
    validate_definition_snapshot,
)
from app.services.agent_mode import UNKNOWN_AGENT_MODE_CODE, UnknownAgentModeError
from app.tools.definitions import get_tool_definition_metadata
from app.tools.registry import TOOL_REGISTRY
from tests.agent_definition_revision_fixtures import admin_user

#: Refused identifier -> current identifier -> the tool already present in the same step whose
#: governed metadata the current identifier must match exactly.
TOOL_REPLACEMENTS = (
    ("grep", "grep_workspace", "read_workspace_file"),
    ("edit_file", "edit_workspace_file", "write_workspace_file"),
    ("multi_edit_file", "multi_edit_workspace_file", "write_workspace_file"),
    ("apply_patch", "apply_patch_workspace", "write_workspace_file"),
)

#: The metadata fields that decide governance: anything that differs between the
#: replacement and the tool the step already had would be a broadening.
GOVERNANCE_FIELDS = (
    "risk",
    "approval_required",
    "mutates_state",
    "filesystem_access",
    "network_access",
    "connector",
    "required_config",
    "scopes",
    "change_only",
    "plan_excluded",
    "audit_required",
    "owner_type",
)


async def _seeded_definition(db: AsyncSession, name: str) -> AgentDefinition:
    definition = (
        await db.execute(select(AgentDefinition).where(AgentDefinition.name == name))
    ).scalars().first()
    assert definition is not None, f"expected the seeded catalog to contain {name!r}"
    return definition


async def test_every_seeded_definition_validates(db: AsyncSession):
    definitions = (await db.execute(select(AgentDefinition))).scalars().all()
    assert definitions

    failures: dict[str, list[dict[str, str]]] = {}
    for definition in definitions:
        steps = await load_definition_steps(db, definition.id)
        result = await validate_definition_snapshot(db, build_definition_snapshot(definition, steps))
        if not result.ok:
            failures[definition.name] = [issue.as_dict() for issue in result.issues]
    assert failures == {}


def test_legacy_tool_identifiers_stay_unknown_and_ungoverned():
    for legacy, _replacement, _precondition in TOOL_REPLACEMENTS:
        assert legacy not in TOOL_REGISTRY
        metadata = get_tool_definition_metadata(legacy)
        assert metadata.risk == "unknown"
        assert metadata.required_config == "tool_definition_metadata"
        assert metadata.approval_required is True


@pytest.mark.parametrize(("legacy", "replacement", "precondition"), TOOL_REPLACEMENTS)
def test_replacement_tool_metadata_matches_a_tool_the_step_already_granted(
    legacy: str, replacement: str, precondition: str
):
    assert replacement in TOOL_REGISTRY
    replacement_metadata = get_tool_definition_metadata(replacement)
    precondition_metadata = get_tool_definition_metadata(precondition)

    observed = {field: getattr(replacement_metadata, field) for field in GOVERNANCE_FIELDS}
    expected = {field: getattr(precondition_metadata, field) for field in GOVERNANCE_FIELDS}
    assert observed == expected, legacy

    # Nothing here may depend on connector activation or extra configuration, which
    # is what "do not bypass activation gating to make seeds pass" means concretely.
    assert replacement_metadata.connector is None
    assert replacement_metadata.required_config is None


async def test_creating_a_definition_with_an_unknown_mode_fails_closed(db: AsyncSession):
    admin = await admin_user(db)
    with pytest.raises(UnknownAgentModeError) as raised:
        await create_agent(
            db,
            user_id=admin.id,
            payload={"name": "Unknown Mode Agent", "agent_type": "self_review"},
            thinking_levels=["off", "light", "deep"],
            serialize_agent_definition=lambda agent: {"id": agent.id},
        )

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == UNKNOWN_AGENT_MODE_CODE
    assert raised.value.detail["field"] == "agent_type"
    assert raised.value.detail["subject"] == "self_review"
    # Nothing was written: the failure precedes the insert.
    assert (
        await db.execute(select(AgentDefinition).where(AgentDefinition.name == "Unknown Mode Agent"))
    ).scalars().first() is None


async def test_updating_a_definition_to_an_unknown_mode_fails_closed(db: AsyncSession):
    admin = await admin_user(db)
    definition = AgentDefinition(owner_id=admin.id, name="Backend helper", agent_type="change")
    db.add(definition)
    await db.commit()

    with pytest.raises(UnknownAgentModeError):
        await update_agent(
            db,
            user_id=admin.id,
            agent_id=definition.id,
            payload={"name": definition.name, "agent_type": "self_review"},
            thinking_levels=["off", "light", "deep"],
            serialize_agent_definition=lambda agent: {"id": agent.id},
        )
    await db.rollback()

    unchanged = await _seeded_definition(db, "Backend helper")
    assert unchanged.agent_type == "change"
