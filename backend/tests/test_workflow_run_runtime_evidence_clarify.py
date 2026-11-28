"""End to end: a simulated device job session runs workflow B from Clarify through the drafted contract to tests first."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import WorkflowRun
from app.services.mcp_parity_dispatch import run_parity_mcp_tool
from app.services.mcp_run_work_item import run_work_item
from app.services.workflow_runs.octryx.stop import run_stop
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture
from tests.workflow_run_runtime_evidence_support import (  # noqa: F401
    PREFIXES,
    _caller,
    _device_session,
    _mcp_row,
    _native,
    _rows,
    _server_pipeline,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")

# --- end to end: B's Clarify from a simulated device job session ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_device_session_runs_b_from_clarify_through_the_drafted_contract_to_tests_first(
        client, auth_headers, db, systems):  # noqa: F811 - the imported fixture
    from tests.workflow_acceptance_support import _settle, _workspace

    project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": "feature-delivery-tdd", "work_item_id": item.id})
    assert started.status_code == 200, started.text
    run_id = started.json()["run"]["id"]
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "clarify"
    run = await db.get(WorkflowRun, run_id)
    working_copy = str(Path(run.context["local_path"]))
    admin = await admin_user(db)
    gateway, key = await _device_session(db, admin, project.id, run_id=run_id, root=working_copy)

    async def stop() -> dict:
        answer = await run_stop(db, session=gateway, hook_input={}, tool_calls=await _rows(db, gateway),
                                test_prefixes=PREFIXES)
        await db.commit()
        return answer

    # Without reading: the gate's evidence is 0/1 and the run stays at Clarify.
    first = await stop()
    assert first["state"] == "blocked" and "The code and the Work item were read" in first["detail"]
    # A read the model only claims (transcript, no hook), one outside the repository and a failed one: still 0/1.
    await _native(db, gateway, "Read", {"file_path": f"{working_copy}/pay/totals.py"}, cwd=working_copy, hook=None)
    await _native(db, gateway, "Read", {"file_path": "/etc/hosts"}, cwd=working_copy)
    await _native(db, gateway, "Read", {"file_path": f"{working_copy}/nope.py"}, cwd=working_copy,
                  hook="PostToolUseFailure")
    second = await stop()
    assert second["state"] == "blocked" and (await db.get(WorkflowRun, run_id)).current_node_id == "clarify"
    # The Work item is readable with the device's own scopes (the run's item only).
    assert (await run_work_item(db, caller=_caller(admin, project.id, key), user=admin, workspace_id=project.id,
                                requested=run.ticket_key)).id == item.id

    # A recorded read inside the repository, the contract only as chat text: still blocked.
    await _native(db, gateway, "Read", {"file_path": f"{working_copy}/pay/totals.py"}, cwd=working_copy)
    third = await stop()
    assert third["state"] == "blocked" and "The test contract was submitted" in third["detail"]
    assert third["workflow_run"]["phase"]["output"] == {"kind": "test_contract", "tool": "submit_test_contract"}

    # The contract as data, over MCP with the device grant's own scopes (no work:manage): a malformed one is refused.
    caller = _caller(admin, project.id, key)
    assert "work:manage" not in caller.scopes
    malformed = await run_parity_mcp_tool(db, caller=caller, tool_name="submit_test_contract",
                                          arguments={"criteria": [{"text": "Totals round half up"}]})
    assert (malformed["state"], malformed["reason"]) == ("invalid_request", "invalid_output")
    contract = {"summary": "Totals round half up", "criteria": [
        {"id": "AC1", "text": "Totals round half up", "tests": ["tests/test_totals.py::test_rounds_half_up"],
         "command": "pytest tests/test_totals.py"},
        {"id": "AC2", "text": "The receipt reads well", "manual_only": True,
         "manual_reason": "Wording is reviewed by a person"}]}
    submitted = await run_parity_mcp_tool(db, caller=caller, tool_name="submit_test_contract", arguments=contract)
    assert (submitted["state"], submitted["version"]) == ("recorded", 1), submitted
    db.add(_mcp_row(gateway, "submit_test_contract", excerpt='{"state": "recorded"}'))
    await db.flush()
    passed = await stop()
    assert passed["state"] == "passed"
    run = await db.get(WorkflowRun, run_id)
    assert run.gate_results["clarify"]["state"] == "passed"
    assert run.current_node_id == "contract" and run.status == "waiting"

    # The server drafted the Work item's change plan (for the requester, with the run's identity) …
    from app.models.runtime.secure_work import WorkChangePlan

    plan = await db.get(WorkChangePlan, run.context["change_plan"]["id"])
    assert (plan.work_item_id, plan.created_by, plan.status) == (item.id, admin.id, "ready_for_review")
    assert plan.evidence_json["workflow_run_id"] == run_id
    assert plan.evidence_json["test_contract_hash"] == run.context["outputs"]["test_contract"]["hash"]
    # … and the confirmation shows exactly that plan: the tests, the command, the manual item it takes over.
    view = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]
    payload = view["waiting"]["payload"]
    assert (payload["change_plan_id"], payload["plan_hash"]) == (plan.id, run.context["change_plan"]["hash"])
    assert payload["acceptance_criteria"][0]["tests"] == ["tests/test_totals.py::test_rounds_half_up"]
    assert (payload["manual_only"], payload["blockers"]) == (["AC2"], [])
    assert [action["key"] for action in view["actions"]][:3] == ["confirm", "change", "stop"]
    confirmed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["run"]["current_node"]["id"] == "tests_first"
    await db.refresh(plan)
    assert plan.status == "approved"
    from sqlalchemy import select

    from app.models.runtime.secure_work import WorkChangePlanDecision

    decision = (await db.execute(select(WorkChangePlanDecision).where(
        WorkChangePlanDecision.change_plan_id == plan.id))).scalar_one()
    assert decision.evidence_json["human_verified_criteria"] == ["AC2"]  # taken over by the confirm, attributed

    # Tests first: the device reads the confirmed contract as the phase's input; the confirmed tests are bound.
    run = await db.get(WorkflowRun, run_id)
    assert run.context["confirmed_tests"] == ["tests/test_totals.py::test_rounds_half_up"]
    from app.services.workflow_runs.octryx.contract import run_contract

    phase = (await run_contract(db, run))["phase"]
    assert phase["node_id"] == "tests_first"
    assert phase["inputs"]["test_contract"]["criteria"][0]["id"] == "AC1" and phase["output"] is None
