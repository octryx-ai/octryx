"""Every registered tool has a definition, so no tool resolves to ``unknown`` risk at runtime."""

import pytest
from sqlalchemy import select

from app.services.approval.resolution_service import resolve_approval_request
from app.services.tool_approval.rules import tool_approval_requirement
from app.tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability
from app.tools.context import ToolContext
from app.tools.definitions import get_all_definitions, get_tool_definition_metadata
from app.tools.registry import TOOL_REGISTRY, execute_tool


def test_every_registered_tool_has_a_definition():
    definitions = get_all_definitions()

    assert sorted(name for name in TOOL_REGISTRY if name not in definitions) == []


def test_every_definition_is_registered():
    assert sorted(name for name in get_all_definitions() if name not in TOOL_REGISTRY) == []


def test_no_registered_or_advertised_tool_resolves_to_unknown_risk():
    names = set(TOOL_REGISTRY) | set(get_all_definitions())
    unknown = sorted(
        name
        for name in names
        if get_tool_definition_metadata(name).risk == "unknown"
        or get_tool_definition_metadata(name).owner_type == "unknown"
    )

    assert unknown == []


def test_ask_reporter_via_teams_is_an_approval_governed_outbound_message():
    metadata = get_tool_definition_metadata("ask_reporter_via_teams")

    assert metadata.owner_type == "built_in"
    assert metadata.risk == "write"
    assert metadata.approval_required is True
    assert metadata.mutates_state is True
    assert metadata.audit_required is True
    assert tool_required_capability("ask_reporter_via_teams") == CAPABILITY_DELIVER
    requirement = tool_approval_requirement("ask_reporter_via_teams", {"approval_policy": {"require_for_risks": ["write"]}})
    assert requirement.required is True
    schema = get_all_definitions()["ask_reporter_via_teams"]["function"]["parameters"]
    assert set(schema["required"]) == {"ticket_id", "reporter_email", "question"}


# ``approval_required`` metadata alone promises nothing: with an empty platform default and no
# Workspace policy the gate would let the message go out. An outward-facing message to a
# person outside the session needs a person's approval on the real dispatch path, whatever the
# policy says, bound to the exact parameters, never waived by an exemption or a standing rule.
REPORTER_PARAMS = {"ticket_id": "BRD-8", "reporter_email": "rep@example.com", "question": "Which locale?"}


@pytest.fixture
def sent(monkeypatch):
    from app.tools.proactive_teams_impl import AskReporterViaTeams

    calls: list[dict] = []

    async def execute(self, params, context):
        calls.append(dict(params))
        return {"success": True, "status": "paused"}

    monkeypatch.setattr(AskReporterViaTeams, "execute", execute)
    return calls


async def _dispatch_context(db, *, run_class: str | None, project_config: dict | None = None) -> ToolContext:
    from app.models import Session as AgentSession
    from app.models import User

    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id=f"reporter-{run_class}-{len(str(project_config))}", user_id=user.id,
                           agent_type="chat", status="active")
    db.add(session)
    await db.flush()
    return ToolContext(
        user_id=user.id, project_ids=[], roles=["member"], session_id=session.id,
        project_config=dict(project_config or {}), db=db,
        run_capability={"enforced": True, "class": run_class} if run_class else None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("run_class", ["deliver", None])
async def test_no_message_goes_out_before_a_person_approves_it(db, sent, run_class):
    context = await _dispatch_context(db, run_class=run_class)

    blocked = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    assert sent == [], "the empty effective policy must not let the message go out"
    assert blocked["approval_required"] is True
    assert blocked["approval_status"] == "pending"
    assert tool_approval_requirement("ask_reporter_via_teams", {}).matched_rule == "outbound_message"


@pytest.mark.asyncio
async def test_the_approval_admits_exactly_the_approved_message_once(db, sent):
    context = await _dispatch_context(db, run_class="deliver")
    blocked = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)
    user_id = context.user_id
    await resolve_approval_request(db, approval_id=blocked["approval_id"], resolved_by=user_id, status="approved")

    changed = await execute_tool("ask_reporter_via_teams", {**REPORTER_PARAMS, "question": "Delete prod?"}, context)
    assert sent == [] and changed["approval_required"] is True, "the grant is bound to the approved parameters"

    result = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)
    assert result.get("success") is True
    [message] = sent
    assert {**message, "question": REPORTER_PARAMS["question"]} == REPORTER_PARAMS
    assert message["question"].startswith(f"{REPORTER_PARAMS['question']}\n\n— Written by an agent")

    again = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)
    assert again["approval_required"] is True and len(sent) == 1, "one approval admits one sequential send (no concurrency guarantee, WP F-5)"


@pytest.mark.asyncio
@pytest.mark.parametrize("run_class", ["read_only", "change"])
async def test_read_only_and_change_runs_never_send(db, sent, run_class):
    context = await _dispatch_context(db, run_class=run_class)

    refused = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    assert sent == []
    assert "approval_id" not in refused
    assert refused.get("error")


def test_no_policy_can_waive_the_outbound_message_approval():
    from app.services.tool_approval.policy import set_platform_default

    set_platform_default({"require_for_risks": [], "require_for_tools": [], "exempt_tools": ["ask_reporter_via_teams"]})
    try:
        requirement = tool_approval_requirement("ask_reporter_via_teams", {"approval_policy": {"mode": "inherit"}})
    finally:
        set_platform_default({})
    assert requirement.required is True
    assert requirement.matched_rule == "outbound_message"


def test_every_outbound_message_tool_is_an_external_write():
    from app.tools.definitions.write_risk import (
        BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
        OUTBOUND_MESSAGE_DEFINITION_NAMES,
    )

    assert "ask_reporter_via_teams" in OUTBOUND_MESSAGE_DEFINITION_NAMES
    assert OUTBOUND_MESSAGE_DEFINITION_NAMES <= BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES
    for name in OUTBOUND_MESSAGE_DEFINITION_NAMES:
        assert tool_approval_requirement(name, {}).required is True, name


@pytest.mark.asyncio
async def test_a_standing_rule_never_answers_an_outbound_message(db, sent, monkeypatch):
    from app.services.standing_approvals.tool_rules import StandingRuleCheck
    from app.services.tool_approval import gate as approval_gate

    async def covered(db, *, session_id, scope):
        return StandingRuleCheck(scope=None, covered=True)

    monkeypatch.setattr(approval_gate, "check_standing_rule", covered)
    context = await _dispatch_context(db, run_class="deliver", project_config={"standing": True})

    blocked = await execute_tool("ask_reporter_via_teams", dict(REPORTER_PARAMS), context)

    assert sent == []
    assert blocked["approval_required"] is True
