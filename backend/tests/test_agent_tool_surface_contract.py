"""The explicit agent tool surface contract: values, conflicts, snapshot, surface, gate.

``governed`` keeps today's behaviour. ``none`` is a deny boundary. It offers no tools, it is
never widened by a selected workflow (that turn stops as ``needs_configuration``), and it never
coexists with steps that use tools.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface
from app.schemas.admin.admin_panel._agents import AgentCreateRequest, AgentUpdateRequest
from app.services.agent_definition_payload import payload_from_snapshot
from app.services.agent_tool_surface_contract import (
    REASON_CODE_INVALID,
    REASON_CODE_STEP_CONFLICT,
    REASON_CODE_WORKFLOW_CONFLICT,
    ToolSurfaceConflictError,
    declared_tool_surface,
    denies_tools,
    ensure_no_step_conflict,
    live_row_tool_surface,
    normalize_tool_surface,
    snapshot_tool_surface,
    snapshot_tool_surface_entry,
)
from app.services.agent_tool_surface_decision import apply_tool_surface_decision_to_profile, evaluate_agent_tool_surface
from app.services.session.execution_gate import evaluate_execution_gate

_ALLOWED_PROFILE = {"status": "allowed", "decision_source": "execution_profile", "reason": "ok"}


def _payload(surface: str | None, steps: list[dict] | None = None) -> dict:
    payload = {"id": "agent-1", "name": "Sum agent", "steps": steps or []}
    if surface is not None:
        payload["toolSurface"] = surface
    return payload


def _surface(agent_definition: dict | None, **overrides):
    plan = plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0)
    kwargs = {
        "capability_type": "diagnosis",
        "workflow_id": None,
        "workflow_contract": None,
        "routing_resolution": None,
        "agent_definition": agent_definition,
        "project_config": {},
        **overrides,
    }
    return resolve_turn_tool_surface(plan, **kwargs)


_SELECTED_DEFINITION = {
    "source": "db",
    "status": "matched",
    "workflow_id": "jira_release_status",
    "tool_policy": {"allowlist": ["list_jira_versions"]},
}


# --- values -------------------------------------------------------------------


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
    # An update without the field keeps the stored value: the key is absent after exclude_none.
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


# --- conflicts ----------------------------------------------------------------


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


# --- tool surface -------------------------------------------------------------


def test_none_offers_no_tools_and_outranks_a_selected_definition():
    plain = _surface(_payload("none"))
    selected = _surface(_payload("none"), routing_resolution=_SELECTED_DEFINITION)
    for plan in (plain, selected):
        assert plan.include_tools is False
        assert plan.tool_allowlist == []
        assert plan.tool_surface_source == "agent_no_tools"


def test_an_unknown_payload_value_fails_closed_to_no_tools():
    plan = _surface(_payload("text"))
    assert plan.include_tools is False
    assert plan.tool_surface_source == "agent_no_tools"


@pytest.mark.parametrize("agent_definition", [None, _payload(None), _payload("governed")])
def test_governed_and_absent_keep_the_governed_default_surface(agent_definition):
    plan = _surface(agent_definition)
    assert plan.include_tools is True
    assert plan.tool_surface_source == "governed_default"
    assert plan.tool_allowlist


def test_governed_keeps_a_selected_definition_surface():
    plan = _surface(_payload("governed"), routing_resolution=_SELECTED_DEFINITION)
    assert plan.tool_surface_source == "selected_definition"
    assert "list_jira_versions" in plan.tool_allowlist


# --- gate ---------------------------------------------------------------------


def test_governed_never_touches_the_profile():
    decision = evaluate_agent_tool_surface(_payload("governed"), workflow_tools_declared=True)
    assert decision.allowed
    assert apply_tool_surface_decision_to_profile(_ALLOWED_PROFILE, decision) == _ALLOWED_PROFILE


def test_plain_none_runs_and_records_its_decision():
    decision = evaluate_agent_tool_surface(_payload("none"), workflow_tools_declared=False)
    profile = apply_tool_surface_decision_to_profile(_ALLOWED_PROFILE, decision)
    assert profile["status"] == "allowed"
    assert profile["requirements"]["agent_tool_surface"]["tool_surface"] == "none"
    assert evaluate_execution_gate(profile).allowed


@pytest.mark.parametrize(
    ("payload", "workflow_tools_declared", "reason_code"),
    [
        (_payload("none"), True, REASON_CODE_WORKFLOW_CONFLICT),
        (_payload("none", [{"name": "S", "isEnabled": True, "allowedTools": ["web_search"]}]), False,
         REASON_CODE_STEP_CONFLICT),
        (_payload("text"), False, REASON_CODE_INVALID),
    ],
)
def test_conflicting_or_unknown_settings_stop_before_model_work(payload, workflow_tools_declared, reason_code):
    decision = evaluate_agent_tool_surface(payload, workflow_tools_declared=workflow_tools_declared)
    profile = apply_tool_surface_decision_to_profile(_ALLOWED_PROFILE, decision)
    assert profile["status"] == "needs_configuration"
    assert profile["reason_code"] == reason_code
    assert profile["decision_source"] == "agent_tool_surface"
    gate = evaluate_execution_gate(profile)
    assert gate.allowed is False
    assert gate.status == "needs_configuration"


def test_an_already_blocked_profile_keeps_its_earlier_reason():
    blocked = {"status": "denied", "decision_source": "routing", "reason": "denied earlier", "reason_code": "x"}
    decision = evaluate_agent_tool_surface(_payload("none"), workflow_tools_declared=True)
    profile = apply_tool_surface_decision_to_profile(blocked, decision)
    assert (profile["status"], profile["reason_code"]) == ("denied", "x")
