"""Contract: answering an exact Work Plan version's open questions creates the next reviewable
version from those answers, or refuses and writes nothing."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog
from app.services.secure_work.plans import clarification_answers as service
from app.services.secure_work.plans.change_plans import decide_change_plan
from app.services.secure_work.plans.plan_write_lock import is_plan_version_conflict, work_item_lock_statement
from app.time_utils import utc_now
from tests.secure_work_plan_clarification_answers_support import (
    QUESTIONS,
    _admin,
    _answer,
    _answers,
    _item,
    _plan,
    _resolver,
    _rows,
)

ALL_QUESTIONS = QUESTIONS + [f"Extra {i}" for i in (3, 4, 5, 6)]


class FakeRuntimeExhaustedError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)
        self.runtime_attempts = [{"status": "error"}]


async def test_answers_create_the_next_version_bound_to_the_exact_source(db):
    actor = await _admin(db)
    item = await _item(db)
    older_open = await _plan(db, item, actor, version=1, status="ready_for_review")
    source = await _plan(db, item, actor, version=2)
    calls: list[dict] = []

    created = await _answer(db, source, actor, calls, open_questions=["Who owns the rollback?"])

    assert len(calls) == 1 and calls[0]["tools"] is None
    assert (calls[0]["max_tokens"], calls[0]["timeout"], calls[0]["effort"]) == (2500, 120.0, "low")
    prompt = calls[0]["messages"][1]["content"]
    assert "Revision of Work Plan version 2" in prompt
    assert "Q1: Which environment is affected?\nA1: Staging only." in prompt
    assert "A3: No flag." in prompt and "Q2 (unanswered): Who owns the rollback?" in prompt

    assert (created["version"], created["status"]) == (3, "needs_clarification")
    assert created["supersedes_plan_id"] == source.id
    assert created["open_questions"] == ["Who owns the rollback?"]
    clarification = created["evidence"]["clarification"]
    assert clarification["source_plan_id"] == source.id and clarification["source_version"] == 2
    assert clarification["answered_by"] == actor.id and clarification["answered_at"]
    assert clarification["answers"] == [
        {"question_index": 0, "question": QUESTIONS[0], "answer": "Staging only."},
        {"question_index": 2, "question": QUESTIONS[2], "answer": "No flag."},
    ]
    assert clarification["unanswered_question_indexes"] == [1]
    assert created["evidence"]["author"] == "llm"

    plans, _ = await _rows(db, item)
    assert plans == [(1, "ready_for_review"), (2, "superseded"), (3, "needs_clarification")], "only the source"
    assert older_open.status == "ready_for_review"
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.resource_id == item.id, AuditLog.action == service.AUDIT_ACTION))
    ).scalar_one()
    assert audit.details["source_plan_id"] == source.id and audit.details["answer_count"] == 2
    assert "Staging only." not in json.dumps(audit.details), "answer text stays in the scoped plan evidence"


@pytest.mark.parametrize(
    ("setup", "expected", "answers", "status", "code"),
    [
        ("newer_version", None, None, 409, "stale_plan_version"),
        ("approved", None, None, 409, "plan_not_open"),
        (None, 3, None, 409, "stale_plan_version"),
        (None, None, [{"question_index": 0, "question": "Which env?", "answer": "x"}], 422, "answer_question_mismatch"),
        (None, None, [{"question_index": 7, "question": QUESTIONS[0], "answer": "x"}], 422, "answer_question_mismatch"),
        (None, None, _answers((0, "a"), (0, "b")), 422, "duplicate_answer"),
        (None, None, _answers((0, "   "), (1, "")), 422, "no_answer"),
        (None, None, _answers((0, "x" * 100_001)), 422, "answer_too_long"),
    ],
)
async def test_refusals_happen_before_any_model_call_and_write_nothing(db, setup, expected, answers, status, code):
    actor = await _admin(db)
    item = await _item(db)
    status_value = "approved" if setup == "approved" else "needs_clarification"
    source = await _plan(db, item, actor, version=1, status=status_value, questions=ALL_QUESTIONS)
    if setup == "newer_version":
        await _plan(db, item, actor, version=2)
    before = await _rows(db, item)
    calls: list[dict] = []

    with pytest.raises(HTTPException) as refused:
        await _answer(db, source, actor, calls, expected=expected, answers=answers)

    assert refused.value.status_code == status and refused.value.detail.startswith(f"{code}: ")
    assert calls == []
    assert await _rows(db, item) == before


async def test_provider_failure_saves_nothing_and_echoes_no_provider_text(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    before = await _rows(db, item)

    async def failing_chat(*_args, **_kwargs):
        raise FakeRuntimeExhaustedError("All runtimes failed: bedrock: AccessDenied for key AKIA-secret-token")

    with pytest.raises(HTTPException) as refused:
        await service.answer_plan_clarifications(
            db, change_plan_id=source.id, current_user=actor, expected_latest_version=1,
            answers=_answers((0, "Staging.")), chat_func=failing_chat, runtime_resolver_func=_resolver,
        )

    assert refused.value.status_code == 503
    assert refused.value.detail.startswith("plan_generation_unavailable: ")
    assert "AKIA" not in refused.value.detail and "bedrock" not in refused.value.detail
    assert refused.value.__cause__ is None and refused.value.__suppress_context__
    assert await _rows(db, item) == before


async def test_an_invalid_model_answer_keeps_the_existing_502_and_saves_nothing(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    before = await _rows(db, item)
    with pytest.raises(HTTPException) as refused:
        await _answer(db, source, actor, [], content="not json")
    assert refused.value.status_code == 502
    assert await _rows(db, item) == before


@pytest.mark.parametrize("change", ["decided", "newer_version", "questions_edited"])
async def test_a_change_committed_during_generation_refuses_after_the_lock(db, change):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)

    async def concurrent_writer():
        # Raw SQL bypasses the session's identity map, like a writer in another transaction:
        # the service must re-read the source instead of trusting the copy loaded before dispatch.
        later = (utc_now() + timedelta(seconds=5)).isoformat(sep=" ")
        if change == "decided":
            await db.execute(text("UPDATE work_change_plans SET status='approved', updated_at=:t WHERE id=:id"),
                             {"t": later, "id": source.id})
        elif change == "questions_edited":
            await db.execute(text("UPDATE work_change_plans SET open_questions_json=:q WHERE id=:id"),
                             {"q": json.dumps(["Different question?"]), "id": source.id})
        else:
            await db.execute(
                text("INSERT INTO work_change_plans (id, work_item_id, version, status, title, assumptions_json, "
                     "open_questions_json, affected_repositories_json, change_units_json, proposed_branches_json, "
                     "planned_files_json, validation_plan_json, acceptance_criteria_json, security_risks_json, "
                     "reviewer_recommendations_json, required_approvals_json, expected_prs_json, trace_refs_json, "
                     "evidence_json, jira_sync_preview_json, created_by, created_at, updated_at) VALUES (:id, :item, 2, "
                     "'ready_for_review', 'v2', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', "
                     "'[]', '[]', '{}', '{}', :actor, :t, :t)"),
                {"id": str(uuid.uuid4()), "item": item.id, "actor": actor.id, "t": later},
            )

    calls: list[dict] = []
    with pytest.raises(HTTPException) as refused:
        await _answer(db, source, actor, calls, during=concurrent_writer)

    assert len(calls) == 1
    assert refused.value.status_code == 409
    assert refused.value.detail.startswith("plan_changed_during_generation: ")
    plans, audits = await _rows(db, item)
    assert 3 not in [version for version, _ in plans] and audits == 0
    assert (1, "superseded") not in plans, "the source is never superseded by a refused answer"


async def test_two_answer_attempts_on_one_version_produce_exactly_one_revision(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    inner_calls: list[dict] = []
    inner: dict = {}

    async def second_attempt_finishes_first():
        inner["plan"] = await _answer(db, source, actor, inner_calls, answers=_answers((1, "The platform team.")))

    with pytest.raises(HTTPException) as refused:
        await _answer(db, source, actor, [], during=second_attempt_finishes_first)
    assert refused.value.status_code == 409 and refused.value.detail.startswith("plan_changed_during_generation: ")

    plans, _ = await _rows(db, item)
    assert plans == [(1, "superseded"), (2, "needs_clarification")], "Q1 and Q3 stay open"
    assert inner["plan"]["evidence"]["clarification"]["answers"][0]["answer"] == "The platform team."

    later_calls: list[dict] = []
    with pytest.raises(HTTPException) as again:
        await _answer(db, source, actor, later_calls)
    assert again.value.detail.startswith("plan_not_open: ") and later_calls == []


async def test_a_decision_validates_the_stored_status_not_a_stale_session_copy(db):
    actor = await _admin(db)
    item = await _item(db)
    plan = await _plan(db, item, actor, version=1, status="ready_for_review")
    await db.execute(text("UPDATE work_change_plans SET status='superseded' WHERE id=:id"), {"id": plan.id})
    assert plan.status == "ready_for_review", "the session copy is stale"

    with pytest.raises(HTTPException) as refused:
        await decide_change_plan(db, change_plan_id=plan.id, current_user=actor,
                                 payload={"action": "approve", "reason": "late approval"})
    assert refused.value.status_code == 409 and "superseded" in refused.value.detail


def test_the_plan_write_lock_is_a_row_lock_on_postgresql():
    sql = str(work_item_lock_statement("item-1").compile(dialect=postgresql.dialect()))
    assert sql.rstrip().endswith("FOR UPDATE") and "FROM work_items" in sql


def test_only_the_plan_version_uniqueness_race_is_a_version_conflict():
    def error(message):
        return IntegrityError("INSERT", {}, Exception(message))

    assert is_plan_version_conflict(error('duplicate key value violates unique constraint "uq_work_change_plans_item_version"'))
    assert is_plan_version_conflict(
        error("UNIQUE constraint failed: work_change_plans.work_item_id, work_change_plans.version"))
    assert not is_plan_version_conflict(error('violates foreign key constraint "work_change_plans_created_by_fkey"'))
    assert not is_plan_version_conflict(error("UNIQUE constraint failed: work_items.source_key"))
