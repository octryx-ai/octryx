"""Canonical DoR absence stays metadata-only through real preview and allocation."""
from __future__ import annotations

import copy

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Session, WorkflowRun, WorkflowRunSession
from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from app.services.workflow_runs.definition_of_ready import validate_record
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.allocation import allocate_child
from app.services.workflow_runs.handoff.authority import confirmed_envelopes
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.handoff.permissions import _scope, rights_evaluator
from app.services.workflow_runs.phase_outputs import output_hash
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.team_handoff_support import action, counts, setup_case

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]


@pytest.fixture(autouse=True)
async def own_tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])


async def metadata_case(db):
    case = await setup_case(db, pool=True)
    case.parent.repository = None
    body = validate_record({"type": "task", "summary": "Read the approved metadata task",
                           "acceptance_criteria": ["Acknowledge in your own child Session"],
                           "complete": True, "open_questions": []})
    assert body["repository"] == "" and body["complete"] is False
    original = case.parent.context["outputs"]["definition_of_ready"]
    envelope = {**original, "record": body, "hash": output_hash(body)}
    case.parent.context = {**case.parent.context, "outputs": {"definition_of_ready": envelope}}
    case.decision.payload = {"subject": "advance", "shows": "definition_of_ready",
                             "output": {"version": 1, "hash": envelope["hash"], **body}}
    case.decision.payload_hash = output_hash(case.decision.payload)
    contract = copy.deepcopy(case.row.contract)
    contract["scope"]["repository"] = None
    case.row.contract = contract
    await db.flush()
    case.row.envelopes = await confirmed_envelopes(db, case.parent, ["definition_of_ready"])
    case.row.payload_hash = canonical_hash(service.binding_payload(case.row))
    await db.flush()
    return case


async def test_normalized_metadata_dor_preview_personal_decline_and_receiver_owned_accept(db):
    case = await metadata_case(db)
    before = await counts(db)
    preview = await service.preview_handoff(db, case.row.id, case.p, rights_evaluator=rights_evaluator)
    assert preview["scope"]["repository"] is None
    assert preview["artefacts"]["definition_of_ready"]["envelope"]["record"]["repository"] == ""
    await service.decline_handoff(db, case.row.id, case.p, action(case.row, "decline"))
    assert case.row.state == "offered" and await counts(db) == before
    await service.preview_handoff(db, case.row.id, case.q, rights_evaluator=rights_evaluator)
    binding = await service.accept_handoff(db, case.row.id, case.q, action(case.row),
                                          rights_evaluator=rights_evaluator, allocator=allocate_child)
    child = await db.get(WorkflowRun, binding["child_run_id"])
    session = await db.get(Session, binding["receiver_session_id"])
    links = (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.run_id == child.id, WorkflowRunSession.active.is_(True)))).scalars().all()
    assert child.repository is None and child.branch is None
    assert child.requested_by == session.user_id == case.q.id and session.parent_session_id is None
    assert len(links) == 1 and links[0].session_id == session.id and links[0].role == "main"
    assert "sender_transcript" not in child.context and "local_path" not in child.context
    assert await counts(db) == tuple(value + 1 for value in before)
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, case.row.id, case.q, action(case.row),
                                    rights_evaluator=rights_evaluator, allocator=allocate_child)
    assert await counts(db) == tuple(value + 1 for value in before)


@pytest.mark.parametrize("repository", [" ", "\t", "bitbucket:other/repo", "bitbucket:demo-team/test", [], 0])
async def test_noncanonical_or_nonempty_repository_never_counts_as_absence(db, repository):
    case = await metadata_case(db)
    envelopes = copy.deepcopy(case.row.envelopes)
    envelopes["definition_of_ready"]["envelope"]["record"]["repository"] = repository
    before = await counts(db)
    with pytest.raises(HTTPException, match="outside the approved scope"):
        await rights_evaluator(db=db, actor=case.q, scope=case.row.contract["scope"],
                               envelopes=envelopes, runtime_target={"kind": "server"})
    assert await counts(db) == before


@pytest.mark.parametrize("kind, envelope_kind, scope_repository", [
    ("test_contract", "test_contract", None),
    ("definition_of_ready", "test_contract", None),
    ("definition_of_ready", "definition_of_ready", "bitbucket:demo-team/test"),
])
async def test_empty_exception_is_only_dor_and_null_approved_repository(db, kind, envelope_kind, scope_repository):
    case = await metadata_case(db)
    scope = {**case.row.contract["scope"], "repository": scope_repository}
    proof = copy.deepcopy(case.row.envelopes["definition_of_ready"])
    proof["envelope"]["kind"] = envelope_kind
    with pytest.raises(HTTPException, match="outside the approved scope"):
        _scope(scope, {kind: proof})
