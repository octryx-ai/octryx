"""The explicit agent tool surface contract: ``governed`` keeps today's behaviour, ``none`` is a deny boundary that
no selected workflow widens."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.admin.admin_panel._agents import AgentCreateRequest, AgentUpdateRequest
from app.services.agent_definition_payload import payload_from_snapshot
from app.services.agent_tool_surface_contract import (
    ToolSurfaceConflictError,
    declared_tool_surface,
    denies_tools,
    ensure_no_step_conflict,
    live_row_tool_surface,
    normalize_tool_surface,
    snapshot_tool_surface,
    snapshot_tool_surface_entry,
)

_ALLOWED_PROFILE = {"status": "allowed", "decision_source": "execution_profile", "reason": "ok"}






_SELECTED_DEFINITION = {
    "source": "db",
    "status": "matched",
    "workflow_id": "jira_release_status",
    "tool_policy": {"allowlist": ["list_jira_versions"]},
}


def test_only_the_two_declared_values_are_accepted_and_only_a_missing_key_means_governed():
    assert normalize_tool_surface("governed") == "governed"
    assert normalize_tool_surface("none") == "none"
    for unknown in (None, "", " none", "text", "NONE", "off", 0, False):
        with pytest.raises(ValueError):
            normalize_tool_surface(unknown)
    assert declared_tool_surface({}) == "governed"
    assert declared_tool_surface({"tool_surface": "none"}) == "none"
    for present in (None, "", "text"):
        with pytest.raises(ValueError):
            declared_tool_surface({"tool_surface": present})


def test_projections_carry_present_invalid_values_verbatim_and_runtime_denies_them():
    assert snapshot_tool_surface({}) == "governed"
    assert snapshot_tool_surface({"tool_surface": ""}) == ""
    assert snapshot_tool_surface({"tool_surface": None}) is None
    # Live rows: None exists only on an unflushed object (NOT NULL column with default governed).
    assert live_row_tool_surface(None) == "governed"
    assert live_row_tool_surface("") == ""
    assert snapshot_tool_surface_entry("") == {"tool_surface": ""}
    for invalid in ("", None, " none", "text"):
        assert denies_tools({"toolSurface": invalid})
    assert not denies_tools({})


def test_panel_write_takes_tool_surface_and_refuses_unknown_values():
    assert AgentCreateRequest(name="a").model_dump()["tool_surface"] == "governed"
    assert AgentCreateRequest(name="a", tool_surface="none").model_dump()["tool_surface"] == "none"
    assert AgentCreateRequest(name="a", toolSurface="none").model_dump()["tool_surface"] == "governed", (
        "the read payload's name is no write field")
    assert "tool_surface" not in AgentUpdateRequest().model_dump(exclude_none=True)
    for body in ({"tool_surface": "text"}, {"tool_surface": ""}, {"tool_surface": None}):
        with pytest.raises(ValidationError):
            AgentUpdateRequest(**body)


def test_snapshots_carry_the_key_only_for_none_so_existing_checksums_stay_stable():
    assert snapshot_tool_surface_entry("governed") == {}
    assert snapshot_tool_surface_entry(None) == {}
    assert snapshot_tool_surface_entry("none") == {"tool_surface": "none"}
    governed = payload_from_snapshot({"name": "a"}, [], definition_id="d1")
    text_only = payload_from_snapshot({"name": "a", "tool_surface": "none"}, [], definition_id="d1")
    assert governed["toolSurface"] == "governed"
    assert text_only["toolSurface"] == "none"


@pytest.mark.parametrize(
    "step",
    [
        {"name": "Look up", "is_enabled": True, "allowed_tools": ["knowledge_search"]},
        {"name": "Look up", "isEnabled": True, "allowedTools": ["knowledge_search"]},
        {"name": "Look up", "is_enabled": True, "step_config": {"tool_use": "required"}},
        # An unrecognised tool_use fails closed to required, exactly like the step guard.
        {"name": "Look up", "is_enabled": True, "step_config": {"tool_use": "maybe"}},
    ],
)
def test_none_refuses_steps_that_use_tools(step):
    with pytest.raises(ToolSurfaceConflictError, match="No tools \\(text only\\) conflicts with .*Look up"):
        ensure_no_step_conflict("none", [step])
    ensure_no_step_conflict("governed", [step])


def test_none_accepts_text_steps_and_disabled_tool_steps():
    ensure_no_step_conflict(
        "none",
        [
            {"name": "Answer", "is_enabled": True, "allowed_tools": [], "step_config": {"tool_use": "optional"}},
            {"name": "Old", "is_enabled": False, "allowed_tools": ["knowledge_search"]},
        ],
    )
















