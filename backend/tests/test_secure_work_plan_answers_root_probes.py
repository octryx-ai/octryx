"""Independent counterprobes for answer revisions on a work plan."""

import uuid

import pytest
from fastapi import HTTPException

from app.models import Project, WorkItemWorkflowDefinition
from tests.secure_work_plan_clarification_answers_support import QUESTIONS, _admin, _answer, _item, _plan


async def test_unanswered_question_survives_model_omission(db):
    actor = await _admin(db)
    item = await _item(db)
    plan = await _plan(db, item, actor, version=1)
    created = await _answer(db, plan, actor, [], open_questions=[])
    assert QUESTIONS[1] in created["open_questions"]
    assert created["status"] == "needs_clarification"


async def test_stored_foreign_workflow_refused_before_dispatch(db):
    actor = await _admin(db)
    own = Project(name=f"answer-own-{uuid.uuid4().hex[:8]}")
    foreign = Project(name=f"answer-foreign-{uuid.uuid4().hex[:8]}")
    db.add_all([own, foreign])
    await db.flush()
    item = await _item(db, project_id=own.id)
    plan = await _plan(db, item, actor, version=1)
    workflow = WorkItemWorkflowDefinition(
        project_id=foreign.id, name="Foreign plan workflow", created_by=actor.id,
    )
    db.add(workflow)
    await db.flush()
    plan.workflow_id = workflow.id
    calls = []
    with pytest.raises(HTTPException) as refused:
        await _answer(db, plan, actor, calls)
    assert refused.value.status_code in {403, 404, 409}
    assert calls == []


async def test_real_model_echo_with_question_label_does_not_duplicate_unanswered_question(db):
    actor = await _admin(db)
    item = await _item(db)
    plan = await _plan(db, item, actor, version=1)
    created = await _answer(db, plan, actor, [], open_questions=[f"Q2: {QUESTIONS[1]}"])
    assert created["open_questions"] == [QUESTIONS[1]]
    assert created["status"] == "needs_clarification"
