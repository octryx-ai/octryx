"""Accepted-spec criteria keep actual receiver authority, stable IDs and honest test proof."""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import func, select

from app.models import WorkflowRunDecision
from app.models.project.knowledge_evidence import KnowledgeSourceHead
from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from app.services.knowledge.access.source_acl import restrict_source
from app.services.workflow_runs.contract_coverage import check_contract_coverage, structured_criteria
from app.services.workflow_runs.specification.engineering_contract import accepted_spec_criteria
from tests.contract_coverage_support import FILE, NEW, REGRESSION, _base_copy, _clarify
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_specification_handoff_authority import accepted_spec_case

pytestmark = pytest.mark.usefixtures("scripted_pool")

SPEC_CRITERIA = [
    {"id": "AC7", "story_ids": ["ST1"], "given": "An admitted source", "when": "I view the claim",
     "then": "I can inspect its exact evidence"},
    {"id": "AC2", "story_ids": ["ST1"], "given": "An unavailable source", "when": "I request its content",
     "then": "Its protected content stays withheld"},
]


@pytest.fixture(autouse=True)
async def handoff_tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])


async def engineering_case(db, tmp_path):
    case = await accepted_spec_case(db, criteria=copy.deepcopy(SPEC_CRITERIA))
    root = tmp_path / "engineering-copy"
    root.mkdir()
    base = _base_copy(root)
    case.child.context = {**case.child.context, "local_path": str(root), "base_sha": base}
    await db.flush()
    return case


def submitted_contract():
    return {"summary": "Proposed tests, awaiting the human contract decision", "open_questions": [], "criteria": [
        {"id": "AC7", "text": "Inspect exact evidence", "tests": [NEW[0]], "test_roles": {NEW[0]: "new"},
         "command": f"python -m pytest {FILE}"},
        {"id": "AC2", "text": "Manual refusal inspection", "manual_only": True,
         "manual_reason": "A person inspects the protected-source refusal in the UI."},
        {"id": "AC99", "text": "Existing behavior", "tests": [REGRESSION[0]],
         "test_roles": {REGRESSION[0]: "regression"}, "command": f"python -m pytest {FILE}"},
    ]}


@pytest.mark.asyncio
async def test_exact_stable_ids_gwt_and_spec_decision_are_projected_without_a_decision(db, tmp_path):
    case = await engineering_case(db, tmp_path)
    before = copy.deepcopy(case.child.context)
    decisions = await db.scalar(select(func.count()).select_from(WorkflowRunDecision))

    record, problems, reason = await check_contract_coverage(db, case.child, submitted_contract(), principal=case.receiver)

    assert not problems and not reason
    source = record["criteria_source"]
    assert source["criteria"] == SPEC_CRITERIA
    assert [row["id"] for row in source["criteria"]] == ["AC7", "AC2"]
    assert source["kind"] == "spec" and source["parent_run_id"] == case.parent.id
    envelope = case.row.envelopes["spec"]["envelope"]
    for key in ("hash", "version", "node_id", "entry"):
        assert source[key] == envelope[key]
    proof = case.row.envelopes["spec"]
    assert source["confirmation"] == {key: proof[key] for key in ("decision_id", "decision_hash", "decided_by")}
    assert source["decided_by"] == case.sender.id
    assert source["binding"]["principal_user_id"] == case.receiver.id
    assert source["accepted_binding"]["actor_id"] == case.receiver.id
    assert source["accepted_binding"]["child_run_id"] == case.child.id
    assert "stays the person's check" in source["note"] and "human confirmation" in source["note"]
    assert case.child.context == before
    assert await db.scalar(select(func.count()).select_from(WorkflowRunDecision)) == decisions
    assert "spec" not in case.child.context.get("outputs", {})
    source["criteria"][0]["given"] = "Changed returned copy"
    assert (await accepted_spec_criteria(db, case.child, principal=case.receiver))["criteria"] == SPEC_CRITERIA


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["renumber", "lowercase", "regression_only", "missing_manual_reason"])
async def test_exact_criterion_needs_its_new_test_or_explicit_manual_reason(db, tmp_path, change):
    case = await engineering_case(db, tmp_path)
    record = submitted_contract()
    if change == "renumber":
        record["criteria"][0]["id"] = "AC1"
    elif change == "lowercase":
        record["criteria"][0]["id"] = "ac7"
    elif change == "regression_only":
        record["criteria"][0].update(tests=[REGRESSION[0]], test_roles={REGRESSION[0]: "regression"})
    else:
        record["criteria"][1]["manual_reason"] = " "

    _, problems, reason = await check_contract_coverage(db, case.child, record, principal=case.receiver)

    assert reason == "invalid_output" and problems
    expected = "AC2:" if change == "missing_manual_reason" else "AC7:"
    assert any(problem.startswith(expected) for problem in problems)


@pytest.mark.asyncio
async def test_relabelled_existing_test_is_not_genuine_new_proof(db, tmp_path):
    case = await engineering_case(db, tmp_path)
    record = submitted_contract()
    record["criteria"][0].update(tests=[REGRESSION[0]], test_roles={REGRESSION[0]: "new"})

    _, problems, reason = await check_contract_coverage(db, case.child, record, principal=case.receiver)

    assert reason == "invalid_output"
    assert any("already exists" in problem for problem in problems)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["no_principal", "wrong_actor", "head", "acl", "missing_proof", "malformed_proof",
                                  "wrong_hash", "wrong_parent", "owner_epoch", "spec_revoked"])
async def test_unresolved_bound_spec_keeps_previous_contract_and_never_uses_dor(db, tmp_path, drift):
    case = await engineering_case(db, tmp_path)
    previous = {"kind": "test_contract", "hash": "previous-contract-hash", "version": 9,
                "record": {"criteria_source": {"source": "previous"}}}
    case.child.context = {**case.child.context, "outputs": {"test_contract": copy.deepcopy(previous)}}
    actor = case.receiver
    if drift == "no_principal":
        actor = None
    elif drift == "wrong_actor":
        actor = case.sender
    elif drift == "head":
        (await db.get(KnowledgeSourceHead, case.source.id)).wanted_revision_id = None
    elif drift == "acl":
        await restrict_source(db, project_id=case.parent.project_id, source_key=case.source.source_key,
                              restriction="restricted", member_emails=(case.sender.email,))
    elif drift == "missing_proof":
        case.child.context = {key: value for key, value in case.child.context.items()
                              if key not in {"handoff", "handoff_approved_envelopes", "handoff_binding"}}
    elif drift == "malformed_proof":
        case.child.context = {**case.child.context, "handoff_approved_envelopes": ["spec"], "handoff": "spec"}
    elif drift == "wrong_hash":
        proof = copy.deepcopy(case.child.context["handoff_approved_envelopes"])
        proof["spec"]["envelope"]["hash"] = "changed"
        case.child.context = {**case.child.context, "handoff_approved_envelopes": proof}
    elif drift == "wrong_parent":
        case.child.parent_run_id = None
    elif drift == "owner_epoch":
        marker = copy.deepcopy(case.child.context["handoff_binding"])
        marker["owner_epoch"] += 1
        case.child.context = {**case.child.context, "handoff_binding": marker}
    else:
        db.add(WorkflowRunDecision(run_id=case.parent.id, kind="confirmation", subject="spec", action="changed",
                                   decided_by=case.sender.id, payload={}, payload_hash="changed"))
    await db.flush()
    proposal = submitted_contract()
    before = copy.deepcopy(proposal)

    returned, problems, reason = await check_contract_coverage(db, case.child, proposal, principal=actor)

    assert reason == "needs_configuration" and problems
    assert returned is proposal and returned == before and "criteria_source" not in returned
    assert case.child.context["outputs"]["test_contract"] == previous
    assert not any("An admitted source" in problem for problem in problems)


@pytest.mark.asyncio
async def test_unreadable_base_refuses_without_treating_absence_as_new_proof(db, tmp_path):
    case = await engineering_case(db, tmp_path)
    case.child.context = {**case.child.context, "base_sha": "unavailable"}
    _, problems, reason = await check_contract_coverage(db, case.child, submitted_contract(), principal=case.receiver)
    assert reason == "needs_configuration" and any("could not be read" in problem for problem in problems)


@pytest.mark.asyncio
async def test_legacy_public_structured_criteria_tuple_and_dor_behavior_remain(db, tmp_path):
    run, _, _ = await _clarify(db, tmp_path, dor=["The existing explicit criterion"])
    criteria, source = await structured_criteria(db, run)
    assert criteria == ["The existing explicit criterion"]
    assert source.startswith("the Work item's confirmed Definition of Ready")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
