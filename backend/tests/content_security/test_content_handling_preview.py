"""The settings preview (``handling_preview``, ``GET .../content-handling``) states what the enforcement points
actually do: every action's preview at the tool-result check and at Command safety equals the runtime disposition
there, and the gateway points show what the gateway's plan applies (credentials only, refuse or report)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.content_routing import tool_result_handling
from app.services.content_security.handling import (
    ACTION_REPORT,
    ACTIONS,
    POINT_COMMANDS,
    POINT_TOOL_RESULTS,
    SURFACE_COMMANDS,
    SURFACE_GATEWAY,
    SURFACE_PLATFORM,
    plan_for,
)
from app.services.content_security.handling_points import OLDER_HISTORY_MASKED, POINTS
from app.services.content_security.handling_preview import fixed_outcomes, surface_actions
from app.services.security_analyzer import content_command

SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"
#: Command safety's finding per previewed action: ``report`` lets the command run with an informational finding.
COMMAND_FINDING = {"review": "review", "deny": "deny", ACTION_REPORT: "allow"}


def _preview(kind: str, settings: dict, point: str) -> dict:
    return next(item for item in surface_actions(kind, settings) if item["surface"] == point)


@pytest.mark.parametrize("action", ACTIONS)
def test_the_tool_result_preview_is_the_tool_result_record(monkeypatch, action):
    recorded: list[dict] = []
    monkeypatch.setattr(tool_result_handling, "record_decision", recorded.append)
    settings = {"email": action}
    handled = tool_result_handling.handle_tool_result(plan_for(settings, SURFACE_PLATFORM), {"email"},
                                                      tool_name="fetch", workspace_id="ws", session_id=None,
                                                      principal="user", counts={"email": 1})
    handled.release(tool_result_handling.RELEASED_BLOCKED if handled.refused else tool_result_handling.RELEASED_UNCHANGED,
                    present=frozenset({"email"}))  # released unchanged: the result carries the email
    handled.write()
    obligation = recorded[-1]["obligation"]
    preview = _preview("email", settings, POINT_TOOL_RESULTS)
    assert (preview["configured_action"], preview["action"]) == (obligation["requested"]["email"],
                                                                 obligation["applied"]["email"])
    deferred = obligation["applies_at"].get("email") == tool_result_handling.APPLIES_AT_MODEL_ENTRANCE
    assert (preview["reason"] == "deferred_to_model_entrance") is deferred
    assert deferred is (action not in ("refuse", ACTION_REPORT))


@pytest.mark.parametrize("action", [*ACTIONS, None])
async def test_the_command_preview_is_command_safety(monkeypatch, action):
    settings = {} if action is None else {"secrets": action}

    async def plan(_scope, surface):
        return plan_for(settings, surface)

    monkeypatch.setattr(content_command, "content_handling_isolated", plan)
    context = SimpleNamespace(project_config={"project_id": "ws"}, project_ids=[])
    finding = await content_command.content_command_analyzer("bash", f"export KEY={SECRET}", context)
    preview = _preview("secrets", settings, POINT_COMMANDS)
    assert preview["configured_action"] == plan_for(settings, SURFACE_COMMANDS).action("secrets")
    assert finding.action == COMMAND_FINDING[preview["action"]], (preview, finding)
    if preview["action"] == ACTION_REPORT:
        assert finding.details["informational"]
    if finding.action == "deny":
        expected = "content_route_unavailable" if action in ("reroute", "mask_reroute") else "content_policy_denied"
        assert finding.details["reason"] == expected


@pytest.mark.parametrize("kind", ["secrets", "credential_assignment", "email", "internal_ip", "iban", "phone"])
@pytest.mark.parametrize("action", [*ACTIONS, None])
def test_the_gateway_preview_is_the_gateways_plan(kind, action):
    """On the gateway only credentials act, by ``refuse`` or ``report`` (defaults: credentials refused, credential
    assignments reported); everything else is shown
    ``platform_calls_only`` with the action the gateway's plan applies instead."""
    settings = {} if action is None else {kind: action}
    applied = plan_for(settings, SURFACE_GATEWAY).action(kind)
    for point in ("gateway_messages", "gateway_responses", "codex_seat"):
        preview = _preview(kind, settings, point)
        assert preview["action"] == applied
        assert preview["configured_action"] == (action or applied)
        assert (preview["reason"] == "platform_calls_only") is (preview["configured_action"] != applied
                                                                or kind not in ("secrets", "credential_assignment"))
        assert preview["conditions"] == []
    default = {"secrets": "refuse", "credential_assignment": "report"}.get(kind, "none")
    assert applied == (action if action in ("refuse", "report") and kind in ("secrets", "credential_assignment")
                       else default)


def test_a_refused_kind_in_older_history_is_shown_masked_on_platform_model_calls():
    """``model_call_fields.refusing`` refuses a kind in the newest turn and the offered tools only; the copy masks it
    everywhere else (``RecordedRun`` masks the refusing kinds too): the preview says so beside both call points."""
    from app.services.content_security import model_call_fields
    from app.services.content_security.model_call_record import SURFACE_REPLAY_ARGUMENTS

    assert SURFACE_REPLAY_ARGUMENTS not in model_call_fields._REFUSING_SURFACES
    assert [point.id for point in POINTS if OLDER_HISTORY_MASKED in point.conditions] == [
        "model_call", "model_call_direct"]
    for point in ("model_call", "model_call_direct"):
        refused = _preview("email", {"email": "refuse"}, point)
        assert (refused["action"], [(rule["where"], rule["action"]) for rule in refused["conditions"]]) == (
            "refuse", [("older_history", "mask")])
        for action in ("mask", ACTION_REPORT, "reroute"):
            assert _preview("email", {"email": action}, point)["conditions"] == []


def test_the_fixed_rules_are_listed_per_point():
    fixed = {point["surface"]: {rule["rule"]: rule["action"] for rule in point["rules"]} for point in fixed_outcomes()}
    assert list(fixed) == [point.id for point in POINTS]
    assert fixed["model_call"] == fixed["model_call_direct"] == {
        "unfinished": "withhold", "unreadable": "refuse", "prompt_injection": "refuse", "final_bytes": "refuse"}
    assert fixed["model_output"] == {"unfinished": "withhold", "unreadable": "refuse", "prompt_injection": "none"}
    assert fixed["tool_results"] == {"unfinished": "withhold", "prompt_injection": "none"}
    for point in ("gateway_messages", "gateway_responses", "codex_seat"):
        assert fixed[point] == {"unfinished": "refuse", "unreadable": "refuse", "prompt_injection": "refuse"}
    assert fixed["commands"] == {"unfinished": "review", "prompt_injection": "none"}


async def test_an_unfinished_command_is_sent_for_review_as_the_preview_says(monkeypatch):
    async def plan(_scope, surface):
        return plan_for({}, surface)

    unfinished = SimpleNamespace(detected=frozenset(), finished=False,
                                 disposition=lambda *, allowed, incomplete: incomplete)
    monkeypatch.setattr(content_command, "content_handling_isolated", plan)
    monkeypatch.setattr(content_command, "examine_text", lambda *_args, **_kwargs: unfinished)
    context = SimpleNamespace(project_config={"project_id": "ws"}, project_ids=[])
    finding = await content_command.content_command_analyzer("bash", "echo ok", context)
    expected = next(point for point in fixed_outcomes() if point["surface"] == POINT_COMMANDS)["rules"][0]
    assert (expected["rule"], expected["action"]) == ("unfinished", finding.action) == ("unfinished", "review")
    assert finding.details["unfinished"] is True
