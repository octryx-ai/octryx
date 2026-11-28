"""Workflow A's Definition of Ready recorded over MCP only within its phase, and workflow E's hypothesis judged against the platform sources, from a device session."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import Message, WorkflowRun
from app.services.mcp_parity_dispatch import PARITY_MCP_TOOLS, run_parity_mcp_tool
from app.services.mcp_workflow_run_tools import mcp_submit_definition_of_ready
from app.services.workflow_runs.octryx.stop import run_stop
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_runtime_evidence_support import (  # noqa: F401
    DEVICE_SCOPES,
    PREFIXES,
    _caller,
    _mcp_row,
    _one_phase,
    _run_with_session,
    _server_pipeline,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")

# --- A: the Definition of Ready over MCP, within the phase ----------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_a_understand_records_the_definition_of_ready_from_a_device_session(db):
    assert PARITY_MCP_TOOLS["submit_definition_of_ready"][1] in DEVICE_SCOPES
    run, gateway, key, workspace_id = await _run_with_session(
        db, _one_phase("jira-intake-triage", "understand", "ready_gate"))
    admin = await admin_user(db)
    args = {"caller": _caller(admin, workspace_id, key), "user": admin, "workspace_id": workspace_id}

    blocked = await run_stop(db, session=gateway, hook_input={}, tool_calls=[], test_prefixes=PREFIXES)
    assert blocked["state"] == "blocked" and "The Definition of Ready was recorded" in blocked["detail"]

    answer = await mcp_submit_definition_of_ready(db, **args, arguments={
        "type": "feature", "summary": "Wrap long lines", "acceptance_criteria": ["wraps at 80"],
        "repository": "github:acme/textkit", "open_questions": []})
    assert {key: answer[key] for key in ("state", "kind", "complete", "missing")} == {
        "state": "recorded", "kind": "definition_of_ready", "complete": True, "missing": []}
    assert run.context["outputs"]["definition_of_ready"]["version"] == 1
    row = _mcp_row(gateway, "submit_definition_of_ready", excerpt='{"state": "recorded"}')
    passed = await run_stop(db, session=gateway, hook_input={}, tool_calls=[row], test_prefixes=PREFIXES)
    assert passed["state"] == "passed"
    run = await db.get(WorkflowRun, run.id)
    assert run.gate_results["ready_gate"]["state"] == "passed" and run.outcome == "done"


@pytest.mark.asyncio
async def test_the_definition_of_ready_is_refused_outside_a_phase_that_offers_it(db):
    _run, gateway, key, workspace_id = await _run_with_session(db, _one_phase("feature-delivery-tdd", "clarify"))
    admin = await admin_user(db)
    refused = await mcp_submit_definition_of_ready(db, caller=_caller(admin, workspace_id, key), user=admin,
                                                   workspace_id=workspace_id, arguments={"type": "task"})
    assert (refused["state"], refused["reason"]) == ("denied", "outside_phase_tools")
    unbound = await mcp_submit_definition_of_ready(db, caller=_caller(admin, workspace_id, None), user=admin,
                                                   workspace_id=workspace_id, arguments={"type": "task"})
    assert unbound["reason"] == "octryx_session_required"


@pytest.mark.asyncio
async def test_a_refused_definition_of_ready_is_a_tool_error_over_mcp(db, monkeypatch):
    import app.services.mcp_parity_registration as registration
    from app.services.mcp_knowledge_protocol import build_knowledge_mcp_server

    async def refused(*_args, **_kwargs):
        return {"state": "denied", "reason": "outside_phase_tools", "message": "no"}

    monkeypatch.setattr(registration, "run_parity_mcp_tool", refused)
    monkeypatch.setattr(registration, "mcp_caller", lambda ctx, authenticate: None)
    from mcp.server.fastmcp.exceptions import ToolError

    # The protocol layer turns a ToolError into an isError result: the transcript records is_error, never evidence.
    with pytest.raises(ToolError, match="outside_phase_tools"):
        await build_knowledge_mcp_server().call_tool("submit_definition_of_ready", {"type": "task", "summary": "x"})


# --- E: the hypothesis cites the platform's sources -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_e_hypothesis_judges_the_observed_answer_against_the_platform_sources(db):
    run, gateway, key, workspace_id = await _run_with_session(db, _one_phase("incident-analysis", "hypothesis"))
    source = "https://kb.example.com/runbooks/payments-timeout"
    # A cut excerpt (the gateway bounds it) still carries its source fields.
    search = _mcp_row(gateway, "knowledge_search",
                      excerpt='{"results": [{"title": "Runbook", "source_url": "' + source + '", "text": "Pool ex')
    admin = await admin_user(db)
    hypothesis = {"summary": "Payments time out after the deploy", "cause": "The connection pool is exhausted.",
                  "impact": "Checkout fails for 5% of users.", "next_step": "Raise the pool size and fix the leak.",
                  "code_fix_needed": True, "sources": [source]}
    submitted = await run_parity_mcp_tool(db, caller=_caller(admin, workspace_id, key),
                                          tool_name="submit_incident_hypothesis", arguments=hypothesis)
    assert submitted["state"] == "recorded", submitted
    search = [search, _mcp_row(gateway, "submit_incident_hypothesis", excerpt='{"state": "recorded"}')]

    async def stop_with(answer: str | None) -> dict:
        if answer is not None:
            db.add(Message(session_id=gateway.id, role="assistant", content=answer,
                           idempotency_key=f"gw:a:{uuid.uuid4().hex}", created_at=utc_now() + timedelta(seconds=2)))
            await db.flush()
        return await run_stop(db, session=gateway, hook_input={}, tool_calls=search, test_prefixes=PREFIXES)

    assert (await stop_with(None))["state"] == "blocked"  # the answer is not observed yet: fail closed
    uncited = await stop_with("The connection pool is exhausted after the deploy.")
    assert uncited["state"] == "blocked" and "The hypothesis cites its evidence" in uncited["detail"]
    # A device cannot cite through the transcript: only gateway-observed answers (gw:a:) count.
    db.add(Message(session_id=gateway.id, role="assistant", content=f"Pool exhausted ([Runbook]({source})).",
                   idempotency_key="device-claim", created_at=utc_now() + timedelta(seconds=3)))
    await db.flush()
    assert (await run_stop(db, session=gateway, hook_input={}, tool_calls=search, test_prefixes=PREFIXES))[
        "state"] == "blocked"
    cited = await stop_with(f"The connection pool is exhausted after the deploy ([Runbook]({source})).")
    assert cited["state"] == "passed"
    run = await db.get(WorkflowRun, run.id)
    recorded = run.context["evidence"]["hypothesis"]
    assert (recorded["cited_count"], recorded["source_count"]) == (1, 1)
    assert run.context["outputs"]["incident_hypothesis"]["record"]["sources"] == [source]
