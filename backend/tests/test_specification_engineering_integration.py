"""The accepted spec in the new engineering B, the spec-origin PM decider and actual-viewer projections."""

from __future__ import annotations

import copy
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, UserProject, WorkflowRunDecision
from app.services.auth.tokens import create_access_token
from app.services.workflow_runs.decider import require_node_decider, resolve_decider
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.phase_outputs import output_hash
from app.services.workflow_runs.records import WorkflowRunError
from tests.contract_coverage_support import FILE, NEW, REGRESSION, _base_copy
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.specification_engineering_graph_support import SPEC_ORIGIN_NODES
from tests.specification_engineering_integration_support import (  # noqa: F401
    SPEC_TEXT,
    _server_pipeline,
    mcp_status,
    tables,
)
from tests.specification_engineering_support import SPEC_CRITERIA, engineering_child_case, enter_node, spec_decision

pytestmark = pytest.mark.usefixtures("scripted_pool")


def headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def decisions(db, run):
    return await db.scalar(select(func.count()).select_from(WorkflowRunDecision)
                           .where(WorkflowRunDecision.run_id == run.id))


async def view(client, run, user):
    response = await client.get(f"/api/v1/workflow-runs/{run.id}", headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()["run"]


def submitted_contract():
    return {"summary": "Proposed tests for the accepted criteria", "open_questions": [], "criteria": [
        {"id": "AC7", "text": "Inspect exact evidence", "tests": [{"id": NEW[0], "role": "new"}],
         "command": f"python -m pytest {FILE}"},
        {"id": "AC2", "text": "Manual refusal inspection", "manual_only": True,
         "manual_reason": "A person inspects the protected-source refusal in the UI."},
        {"id": "AC99", "text": "Existing behaviour", "tests": [{"id": REGRESSION[0], "role": "regression"}],
         "command": f"python -m pytest {FILE}"}]}


async def coverage_case(db, tmp_path):
    from app.services.workflow_runs.phase_outputs import submit_output

    case = await engineering_child_case(db)
    root = tmp_path / "engineering-copy"
    root.mkdir()
    case.child.context = {**case.child.context, "local_path": str(root), "base_sha": _base_copy(root)}
    await enter_node(db, case.child, "clarify")
    answer = await submit_output(db, case.child, "submit_test_contract", submitted_contract(), principal=case.engineer)
    assert answer["state"] == "recorded", answer
    await db.commit()
    await enter_node(db, case.child, "contract")
    return case


@pytest.mark.asyncio
async def test_test_contract_card_shows_the_exact_spec_coverage_to_permitted_viewers_only(db, client, tmp_path):
    case = await coverage_case(db, tmp_path)
    record = case.child.context["outputs"]["test_contract"]["record"]
    assert record["criteria_source"]["kind"] == "spec" and record["criteria_source"]["decided_by"] == case.pm.id
    payload = case.child.node_state["waiting"]["payload"]
    assert payload["shows"] == "spec" and payload["output"]["criteria"] == SPEC_CRITERIA
    assert payload["accepted_spec"]["decided_by"] == case.pm.id
    assert payload["accepted_spec"]["parent_run_id"] == case.parent.id
    assert {row["id"]: row["covered"] for row in payload["coverage"]} == {"AC7": True, "AC2": True}
    assert payload["coverage"][0]["new_tests"] and payload["coverage"][1]["manual_reason"]
    for viewer in (case.engineer, case.pm):
        seen = await view(client, case.child, viewer)
        assert seen["waiting"]["payload"]["output"]["criteria"] == SPEC_CRITERIA
        assert seen["waiting"]["payload_hash"] == case.child.node_state["waiting"]["payload_hash"]
    denied = await view(client, case.child, case.denied)
    assert denied["waiting"]["payload_hash"] is None and denied["waiting"]["payload"]["missing"]
    assert SPEC_TEXT not in json.dumps(denied) and case.source.id not in json.dumps(denied)
    terminal = (await mcp_status(db, case.child, case.denied))["decision"]
    assert not terminal["payload_hash"] and "confirm" not in terminal["actions"]
    assert SPEC_TEXT not in json.dumps(terminal)
    assert (await mcp_status(db, case.child, case.engineer))["decision"]["payload"]["output"]["criteria"]


@pytest.mark.asyncio
async def test_wrong_actors_cannot_decide_the_engineers_contract_card(db, client, tmp_path):
    case = await coverage_case(db, tmp_path)
    card_hash = case.child.node_state["waiting"]["payload_hash"]
    count = await decisions(db, case.child)
    for actor, status in ((case.pm, 403), (case.denied, 403), (case.sender, 403)):
        response = await client.post(f"/api/v1/workflow-runs/{case.child.id}/actions", headers=headers(actor),
                                     json={"action": "change", "payload_hash": card_hash})
        assert response.status_code == status, response.text
    await db.refresh(case.child)
    assert await decisions(db, case.child) == count and case.child.current_node_id == "contract"


@pytest.mark.asyncio
async def test_spec_origin_is_the_exact_spec_confirmer_never_the_requester_or_idea_confirmer(db):
    case = await engineering_child_case(db)
    graph = await graph_for_run(db, case.child)
    assert case.pm.id not in {case.sender.id, case.engineer.id} and case.child.requested_by == case.engineer.id
    idea = [row for row in (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.parent.id))).scalars() if row.payload.get("shows") == "idea_frame"]
    assert idea and {row.decided_by for row in idea} == {case.sender.id}
    for node_id in SPEC_ORIGIN_NODES:
        resolution = await resolve_decider(db, case.child, graph.nodes[node_id])
        assert (resolution.policy, resolution.user_ids, resolution.reason) == ("spec_origin", (case.pm.id,), "")
    contract = await resolve_decider(db, case.child, graph.nodes["contract"])
    assert contract.user_ids == (case.engineer.id,) and contract.policy == "requester"
    assert case.child.requested_by == case.engineer.id


@pytest.mark.asyncio
@pytest.mark.parametrize("drift,reason", [
    ("pm_membership", "spec_origin_inactive"), ("spec_reconfirmed", "spec_origin_unresolved"),
    ("decision_rewritten", "spec_origin_unresolved"), ("owner_epoch", "spec_origin_unresolved"),
    ("owner_membership", "spec_origin_unresolved"), ("missing_marker", "spec_origin_unresolved"),
    ("head", "spec_origin_unresolved")])
async def test_spec_origin_drift_needs_configuration_and_never_falls_back(db, drift, reason):
    from app.models.project.knowledge_evidence import KnowledgeSourceHead

    case = await engineering_child_case(db)
    if drift == "pm_membership":
        await db.delete((await db.execute(select(UserProject).where(UserProject.user_id == case.pm.id))).scalar_one())
    elif drift == "spec_reconfirmed":
        payload = {"shows": "spec", "output": {}}
        db.add(WorkflowRunDecision(run_id=case.parent.id, kind="confirmation", subject="advance", action="changed",
                                   payload=payload, payload_hash=output_hash(payload), decided_by=case.sender.id))
    elif drift == "decision_rewritten":
        (await spec_decision(db, case.parent)).decided_by = case.engineer.id
    elif drift == "owner_membership":
        await db.delete((await db.execute(select(UserProject).where(
            UserProject.user_id == case.engineer.id))).scalar_one())
    elif drift == "head":
        (await db.get(KnowledgeSourceHead, case.source.id)).wanted_revision_id = None
    else:
        context = copy.deepcopy(case.child.context)
        if drift == "owner_epoch":
            context["handoff_binding"]["owner_epoch"] += 1
        else:
            del context["handoff_binding"]
        case.child.context = context
    await db.flush()
    node = (await graph_for_run(db, case.child)).nodes["accept_functional"]
    resolution = await resolve_decider(db, case.child, node)
    assert resolution.user_ids == () and resolution.reason == reason and not resolution.configured
    assert not any(resolution.allows(user.id) for user in (case.engineer, case.sender, case.pm))


@pytest.mark.asyncio
async def test_final_recheck_routes_pm_decisions_and_keeps_engineer_confirmations(db):
    case = await engineering_child_case(db)
    await enter_node(db, case.child, "accept_functional")
    assert (await require_node_decider(db, case.child, case.pm)).policy == "spec_origin"
    for actor in (case.engineer, case.sender, case.denied):
        with pytest.raises(WorkflowRunError) as error:
            await require_node_decider(db, case.child, actor)
        assert error.value.code == "not_decider"
    await db.rollback()
    await db.refresh(case.child)
    await enter_node(db, case.child, "retry")
    assert (await require_node_decider(db, case.child, case.engineer)).policy == "requester"
    with pytest.raises(WorkflowRunError):
        await require_node_decider(db, case.child, case.pm)


@pytest.mark.asyncio
async def test_pm_decides_functional_acceptance_over_http_while_the_engineer_keeps_execution(db, client):
    case = await engineering_child_case(db)
    await enter_node(db, case.child, "accept_functional")
    card_hash = case.child.node_state["waiting"]["payload_hash"]
    pm_view = await view(client, case.child, case.pm)
    assert {"reject_acceptance", "not_testable_yet"} <= {item["key"] for item in pm_view["actions"]}
    assert pm_view["waiting"]["payload_hash"] == card_hash
    engineer_view = await view(client, case.child, case.engineer)
    assert "reject_acceptance" not in {item["key"] for item in engineer_view["actions"]}
    denied = await view(client, case.child, case.denied)
    assert denied["waiting"]["payload_hash"] is None
    count = await decisions(db, case.child)
    body = {"action": "reject_acceptance", "payload_hash": card_hash, "reason": "Not the specified behaviour"}
    for actor in (case.engineer, case.sender, case.denied):
        refused = await client.post(f"/api/v1/workflow-runs/{case.child.id}/actions", headers=headers(actor), json=body)
        assert refused.status_code == 403, refused.text
    assert await decisions(db, case.child) == count
    response = await client.post(f"/api/v1/workflow-runs/{case.child.id}/actions", headers=headers(case.pm), json=body)
    assert response.status_code == 200, response.text
    await db.refresh(case.child)
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.child.id,
        WorkflowRunDecision.subject == "functional_acceptance"))).scalar_one()
    assert decision.decided_by == case.pm.id and decision.action == "rejected"
    assert decision.payload_hash and case.child.current_node_id == "followup_intent"
    assert case.child.requested_by == case.engineer.id
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_decider.decision",
                                                     AuditLog.resource_id == case.child.id))).scalar_one()
    assert audit.user_id == case.pm.id and audit.details["policy"] == "spec_origin"
    assert audit.details["execution_user_id"] == case.engineer.id


@pytest.mark.asyncio
async def test_pm_without_own_source_authority_sees_nothing_and_decides_nothing(db, client):
    case = await engineering_child_case(db)
    await enter_node(db, case.child, "accept_functional")
    card_hash = case.child.node_state["waiting"]["payload_hash"]
    pm = await db.get(type(case.pm), case.pm.id)
    pm.email = f"renamed-{uuid.uuid4().hex[:6]}@example.com"
    await db.commit()
    node = (await graph_for_run(db, case.child)).nodes["accept_functional"]
    assert (await resolve_decider(db, case.child, node)).user_ids == (case.pm.id,)
    seen = await view(client, case.child, pm)
    assert seen["waiting"]["payload_hash"] is None and seen["waiting"]["payload"]["missing"]
    count = await decisions(db, case.child)
    response = await client.post(f"/api/v1/workflow-runs/{case.child.id}/actions", headers=headers(pm),
        json={"action": "reject_acceptance", "payload_hash": card_hash, "reason": "Not the specified behaviour"})
    assert response.status_code == 409, response.text
    assert SPEC_TEXT not in response.text
    await db.refresh(case.child)
    assert await decisions(db, case.child) == count and case.child.current_node_id == "accept_functional"
    assert case.child.status == "waiting"


@pytest.mark.asyncio
async def test_publication_dispatch_rechecks_the_confirmers_own_source_authority(db):
    from app.services.workflow_runs.documentation.decision_authority import publication_decision_problem
    from app.services.workflow_runs.pause import payload_hash

    case = await engineering_child_case(db)
    payload = {"subject": "publication", "body": "page"}
    decision = WorkflowRunDecision(run_id=case.child.id, node_id="confirm_publication", kind="confirmation",
        subject="publication", action="confirmed", payload=payload, payload_hash=payload_hash(payload),
        decided_by=case.pm.id)
    db.add(decision)
    await db.flush()
    assert await publication_decision_problem(db, case.child, decision) == ""
    decision.decided_by = case.engineer.id
    assert "authority" in await publication_decision_problem(db, case.child, decision)
    decision.decided_by = case.pm.id
    (await db.get(type(case.pm), case.pm.id)).email = "renamed-pm@example.com"
    await db.flush()
    assert "sources" in await publication_decision_problem(db, case.child, decision)
