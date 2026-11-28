"""One act from Claude Code or from Codex: the platform decides it the same (the shared table scenarios.json plus
the cross-engine paths: check attempts, Stop verification, agent marking, gateway content)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.models import User
from app.services.ai_marking import MarkingFacts, marker_line
from app.services.content_routing.gateway_outcome import GatewayOutcome
from app.services.content_security.enforcement_inbound import InboundRequest, enforce_inbound
from app.services.devices.device_runs_keys import DEFAULTS
from app.services.policy_engine.schema import ROUTE_SEAT
from app.services.workflow_runs.phase_outputs import OUTPUTS_KEY
from app.services.workflow_runs.plan_scope import validate_change_plan
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.time_utils import utc_now
from app.tools.context import ToolContext
from tests.conformance.engine_bodies import BODIES, CODEX, ENGINES, SCENARIOS, tag
from tests.content_security.gateway_route_support import SEAT_MODEL, configure, messages_body, responses_body
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.agent_gateway.test_agent_gateway_control_plane import (
    BASE,
    VERIFYING_POLICY,
    _gateway,
    _gateway_row,
    _workspace,
)
from tests.test_workflow_run_pause import _turn
from tests.workflow_run_octryx_support import _bound_run, _decide, _fix_definition, set_tool_defaults

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


async def _engine_run(db, engine: str):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    tag(gateway, engine)
    await db.flush()
    return run, gateway, key, workspace_id


async def _decided(db, scenario: dict, engine: str) -> dict:
    run, gateway, key, workspace_id = await _engine_run(db, engine)
    setup = scenario.get("setup") or {}
    if "change_plan" in setup:
        record, problems = validate_change_plan(setup["change_plan"])
        assert problems == []
        run.context = {**dict(run.context or {}), OUTPUTS_KEY: {"change_plan": {"record": record}}}
    if "tool_defaults" in setup:
        await set_tool_defaults(db, workspace_id, **setup["tool_defaults"])
    await db.flush()
    answer: dict = {}
    for body in BODIES[engine](scenario[engine]):  # the launcher answers a split patch with its first denial
        answer = await _decide(db, gateway, key, workspace_id, body)
        if answer["decision"] == "deny":
            break
    await db.refresh(run)
    return {"decision": answer["decision"], "reason": answer.get("reason"), "status": run.status,
            "pause": run.pause_reason}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[item["id"] for item in SCENARIOS])
async def test_both_engines_get_the_same_decision_as_the_table_expects(db, scenario):
    claude, codex = [await _decided(db, scenario, engine) for engine in ENGINES]
    assert claude == codex
    expect = scenario["expect"]
    assert claude == {**expect, "status": "paused" if expect["pause"] else "running"}


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ENGINES)
async def test_a_red_gate_stops_in_checks_failed_after_three_attempts(db, engine):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    tag(session, engine)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition(max_iterations=10)),
                          project_id=workspace_id, session=session)
    session_id = await main_session_id(db, run)
    for _ in range(DEFAULTS["check_attempts"] + 1):
        await _turn(db, session_id, ["knowledge_search"])

    assert (run.status, run.pause_reason) == ("paused", "checks_failed")
    pause = run.node_state["pause"]
    assert [item["check"] for item in pause["checks"]] == ["tool_called"]
    assert "failed 3 of 3 attempts" in pause["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ENGINES)
async def test_the_stop_verification_reads_the_same_state(client, db, engine):
    headers, session = await _gateway(db, await _workspace(db, policy=VERIFYING_POLICY))
    tag(session, engine)
    await db.commit()
    start = utc_now()

    async def verify() -> tuple[str, str | None]:
        response = await client.post(f"{BASE}/sessions/verification", headers=headers,
                                     json={"hook_event_name": "Stop", "stop_hook_active": False})
        assert response.status_code == 200
        return response.json()["state"], response.json().get("reason")

    db.add(_gateway_row(session, "Edit", at=start, is_error=False))
    await db.commit()
    assert await verify() == ("blocked", "no_test_after_last_change")
    db.add(_gateway_row(session, "Bash", at=start + timedelta(seconds=1), is_error=False, command="pytest tests/x.py"))
    await db.commit()
    assert (await verify())[0] == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ENGINES)
async def test_a_marked_write_carries_the_same_line(db, monkeypatch, engine):
    import app.tools.registry as registry

    run, gateway, _key, _workspace_id = await _engine_run(db, engine)
    seen: list[dict] = []

    async def gate(_tool, params, _context):
        seen.append(params)
        return {"error": "blocked for the test"}

    monkeypatch.setattr(registry, "_run_governed_tool_checks", gate)
    context = ToolContext(user_id=run.requested_by, project_ids=[], roles=[], session_id=gateway.id,
                          project_config={}, db=db)
    await registry.execute_tool("add_jira_comment", {"ticket_id": "OPS-2", "body": "Done"}, context)

    owner = await db.get(User, run.requested_by)
    assert seen == [{"ticket_id": "OPS-2",
                     "body": f"Done\n\n{marker_line(MarkingFacts(responsible=owner.display_name))}"}]


SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"
EMAIL = "jane.doe@example.org"
SEAT_BODIES = {"claude": messages_body, CODEX: responses_body}
GATEWAY_CASES = {
    "secret_masked_by_default": (None, f"deploy with {SECRET}", (None, {"secrets": "mask"}, False)),
    "secret_refused_when_set": (("secrets", "refuse"), f"deploy with {SECRET}",
                                ("secret_detected_in_prompt", {"secrets": "refuse"}, None)),
    "email_allowed_and_recorded": (None, f"mail {EMAIL}", (None, {"email": "report"}, True)),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("case", sorted(GATEWAY_CASES))
async def test_seat_content_gets_the_same_outcome(db, engine, case):
    setting, text, expected = GATEWAY_CASES[case]
    workspace_id = await seed_workspace(db)
    if setting is not None:
        await configure(db, workspace_id, *setting)
    outcome = GatewayOutcome()
    body = SEAT_BODIES[engine](SEAT_MODEL, newest=text)
    plan = await enforce_inbound(db, InboundRequest(body=body, outcome=outcome, route=ROUTE_SEAT,
                                                 workspace_id=workspace_id, conversation="c", alias=SEAT_MODEL))
    found = text.split()[-1]
    sent = None if plan.body is None else found in json.dumps(plan.body)
    assert (plan.refusal.reason if plan.refusal else None, outcome.requested, sent) == expected
