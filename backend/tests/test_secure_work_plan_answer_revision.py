"""Contract: what a clarification-answer revision carries and refuses.

- unanswered source questions stay open in the revision whatever the model returns, deduplicated,
  and keep it ``needs_clarification``;
- the prompt carries the exact source plan's bounded context; a field that does not fit is named
  as omitted, never cut;
- the source plan's stored workflow is loaded through the scoped loader for the item's Workspace (missing or
  invisible: the same 404; an authorized workflow of another Workspace: the workflow mismatch 409) and must be
  active, checked before any model call;
- the answering actor is retained with a readable label;
- the engine's real exhausted-runtime error becomes a 503 without provider text.

The model is faked except in the exhaustion test, which runs the real runtime fallback chain against
a failing provider client.
"""

from __future__ import annotations

import uuid
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
from app.models import Project, UserProject, WorkChangePlan, WorkItemWorkflowDefinition
from app.services.secure_work.plans import clarification_answers as service
from app.services.secure_work.plans.clarification_revision import revision_open_questions
from app.services.secure_work.workflow_access import WORKFLOW_NOT_FOUND
from tests.jira_task_list_support import _operator
from tests.secure_work_plan_clarification_answers_support import (
    QUESTIONS,
    _admin,
    _answer,
    _answers,
    _item,
    _plan,
    _rows,
)

ALL_ANSWERED = _answers((0, "Staging only."), (1, "The platform team."), (2, "No."))


async def test_model_omission_and_duplicates_keep_unanswered_source_questions_open(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    generated = ["  who owns THE rollback? ", "Which on-call rota applies?", "Which on-call rota applies?"]

    created = await _answer(db, source, actor, [], open_questions=generated)

    assert created["open_questions"] == [QUESTIONS[1], "Which on-call rota applies?"]
    assert created["status"] == "needs_clarification"
    assert created["evidence"]["clarification"]["carried_open_questions"] == [QUESTIONS[1]]


# A real model call echoes the unanswered question with the prompt's own label.
LIVE_SOURCE = [
    "Which repository holds the change?",
    "Which engineering profiles should be available for reviewer recommendation?",
]
LIVE_ECHO = "Q2: Which engineering profiles should be available for reviewer recommendation?"


@pytest.mark.parametrize(
    "echo",
    [
        LIVE_ECHO,
        "Q2 (unanswered): Which engineering profiles should be available for reviewer recommendation?",
        "  q2:   which ENGINEERING profiles should be available for reviewer recommendation? ",
        "Q7: Which engineering profiles should be available for reviewer recommendation?",
    ],
)
def test_a_prompt_labelled_echo_matches_its_source_question_and_keeps_the_source_text(echo):
    source = SimpleNamespace(open_questions_json=list(LIVE_SOURCE))
    answers = [{"question_index": 0, "question": LIVE_SOURCE[0], "answer": "demo-infra"}]
    merged, carried = revision_open_questions(source, answers, [echo, "Who approves the change window?"])
    assert merged == [LIVE_SOURCE[1], "Who approves the change window?"]
    assert carried == [LIVE_SOURCE[1]]


@pytest.mark.parametrize(
    "distinct",
    [
        "Q2: Which reviewer groups should be available for reviewer recommendation?",
        "Q2 Which engineering profiles should be available for reviewer recommendation?",
        "Question 2: Which engineering profiles should be available for reviewer recommendation?",
        "Q2: Q2: Which engineering profiles should be available for reviewer recommendation?",
        "Note: Which engineering profiles should be available for reviewer recommendation?",
    ],
)
def test_other_wording_or_label_shapes_stay_distinct_and_unchanged(distinct):
    source = SimpleNamespace(open_questions_json=list(LIVE_SOURCE))
    answers = [{"question_index": 0, "question": LIVE_SOURCE[0], "answer": "demo-infra"}]
    merged, _ = revision_open_questions(source, answers, [distinct])
    assert merged == [LIVE_SOURCE[1], distinct], "only the exact prompt label is ignored; text is never rewritten"


async def test_the_live_echo_shape_produces_one_open_question_end_to_end(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1, questions=LIVE_SOURCE)
    created = await _answer(
        db, source, actor, [],
        answers=[{"question_index": 0, "question": LIVE_SOURCE[0], "answer": "demo-infra"}],
        open_questions=[LIVE_ECHO],
    )
    assert created["open_questions"] == [LIVE_SOURCE[1]]
    assert created["status"] == "needs_clarification"
    clarification = created["evidence"]["clarification"]
    assert clarification["carried_open_questions"] == [LIVE_SOURCE[1]]
    assert clarification["source_plan_id"] == source.id and clarification["unanswered_question_indexes"] == [1]


async def test_all_answered_and_no_new_question_is_ready_for_review(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    created = await _answer(db, source, actor, [], answers=ALL_ANSWERED, open_questions=[])
    assert (created["open_questions"], created["status"]) == ([], "ready_for_review")
    assert created["evidence"]["clarification"]["carried_open_questions"] == []


async def test_the_prompt_revises_the_exact_source_plan_with_every_field_whole(db):
    """No artificial limits: a long field reaches the revision whole."""
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    source.understood_request = "Clean the demo-infra Terraform after the pipeline split."
    source.affected_repositories_json = [{"repository_name": "demo-infra", "scope": "terraform/"}]
    source.planned_files_json = [{"repository_name": "demo-infra", "paths": ["x" * 12010]}]
    source.evidence_json = {"plan_type": "configuration_change"}
    await db.flush()
    calls: list[dict] = []

    created = await _answer(db, source, actor, calls)

    prompt = calls[0]["messages"][1]["content"]
    assert "Revision of Work Plan version 1" in prompt
    assert "Clean the demo-infra Terraform after the pipeline split." in prompt
    assert '"repository_name": "demo-infra", "scope": "terraform/"' in prompt
    assert "Omitted from the source plan" not in prompt and "x" * 12010 in prompt
    record = created["evidence"]["clarification"]["source_context"]
    assert record["omitted_fields"] == []
    assert record["included_fields"][:3] == ["understood_request", "plan_type", "affected_repositories"]
    assert calls[0]["tools"] is None


async def _project(db, label):
    project = Project(name=f"answer-{label}-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    return project


@pytest.mark.parametrize(
    ("workflow_project", "active", "item_has_project", "viewer", "outcome"),
    [
        ("own", True, True, "admin", "allowed"),
        ("global", True, True, "admin", "allowed"),
        ("global", True, False, "admin", "allowed"),
        ("foreign", True, True, "admin", (409, "workflow_project_mismatch")),
        ("blank", True, True, "admin", (409, "workflow_project_mismatch")),
        ("foreign", True, False, "admin", (409, "workflow_project_mismatch")),
        ("own", False, True, "admin", (409, "source_workflow_inactive")),
        ("missing", True, True, "admin", (404, WORKFLOW_NOT_FOUND)),
        ("own", True, True, "member", "allowed"),
        ("foreign", True, True, "member", (404, WORKFLOW_NOT_FOUND)),  # invisible: the answer of a missing one
        ("missing", True, True, "member", (404, WORKFLOW_NOT_FOUND)),
    ],
)
async def test_the_source_workflow_is_read_through_the_scoped_loader_before_dispatch(
    db, workflow_project, active, item_has_project, viewer, outcome
):
    actor = await _admin(db)
    own, foreign = await _project(db, "own"), await _project(db, "foreign")
    item = await _item(db, project_id=own.id if item_has_project else None)
    source = await _plan(db, item, actor, version=1)
    if workflow_project == "missing":
        source.workflow_id = str(uuid.uuid4())
    else:
        project_id = {"own": own.id, "foreign": foreign.id, "global": None, "blank": ""}[workflow_project]
        workflow = WorkItemWorkflowDefinition(
            project_id=project_id, name=f"wf-{workflow_project}", created_by=actor.id, is_active=active
        )
        db.add(workflow)
        await db.flush()
        source.workflow_id = workflow.id
    if viewer == "member":
        actor = await _operator(db)
        db.add(UserProject(user_id=actor.id, project_id=own.id, role="admin"))
    await db.flush()
    before = await _rows(db, item)
    calls: list[dict] = []

    if outcome == "allowed":
        created = await _answer(db, source, actor, calls)
        assert created["workflow_id"] == source.workflow_id and len(calls) == 1
        return
    with pytest.raises(HTTPException) as refused:
        await _answer(db, source, actor, calls)
    status, code = outcome
    detail = refused.value.detail
    assert refused.value.status_code == status
    assert (detail["code"] if isinstance(detail, dict) else detail.split(": ")[0]) == code
    assert calls == []
    assert await _rows(db, item) == before


async def test_the_answering_actor_is_retained_with_a_readable_label(db):
    actor = await _admin(db)
    item = await _item(db)
    created = await _answer(db, await _plan(db, item, actor, version=1), actor, [])
    clarification = created["evidence"]["clarification"]
    assert clarification["answered_by"] == actor.id
    assert clarification["answered_by_label"] == (actor.display_name or actor.username)


async def test_real_runtime_exhaustion_is_a_503_without_provider_text(db):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    before = await _rows(db, item)

    class FailingClient:
        async def chat(self, **_kwargs):
            raise RuntimeError("AccessDeniedException: key AKIA-SECRET-123 denied by bedrock")

    async def resolver(_db, *, runtime_target_id=None):
        return [{"target_id": "rt-1", "provider_id": "p-1", "provider_name": "bedrock", "driver": "bedrock",
                 "model": "plan-model", "priority": 1, "max_runtime_retries": 0, "max_malformed_retries": 0,
                 "max_context_retries": 0}]

    chat = partial(_chat_with_runtime_fallback, get_provider_func=lambda **_kwargs: FailingClient())
    with pytest.raises(HTTPException) as refused:
        await service.answer_plan_clarifications(
            db, change_plan_id=source.id, current_user=actor, expected_latest_version=1,
            answers=_answers((0, "Staging.")), chat_func=chat, runtime_resolver_func=resolver,
        )

    assert refused.value.status_code == 503
    detail = refused.value.detail
    assert detail.startswith("plan_generation_unavailable: ")
    assert not any(secret in detail for secret in ("AKIA", "AccessDenied", "bedrock", "plan-model"))
    assert refused.value.__cause__ is None
    assert await _rows(db, item) == before
    assert (await db.get(WorkChangePlan, source.id)).status == "needs_clarification"
