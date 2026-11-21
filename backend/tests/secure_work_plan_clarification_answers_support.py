"""Shared Work Plan, answer and fake-model helpers for the Work Plan clarification answer tests and their importers."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select

from app.models import AuditLog, User, WorkChangePlan, WorkItem
from app.services.secure_work.plans import clarification_answers as service

QUESTIONS = ["Which environment is affected?", "Who owns the rollback?", "Is a feature flag required?"]


async def _resolver(_db, *, runtime_target_id=None):
    return [{"target_id": "runtime-1", "provider_id": "p-1", "provider_name": "bedrock", "model": "plan-model"}]


def _chat(calls: list[dict], *, open_questions=None, content=None, during=None):
    async def chat(runtimes, *, messages, tools, max_tokens, reasoning_effort, request_timeout_seconds):
        calls.append({"messages": messages, "tools": tools, "max_tokens": max_tokens,
                      "timeout": request_timeout_seconds, "effort": reasoning_effort})
        if during is not None:
            await during()
        body = content if content is not None else json.dumps({
            "plan_type": "configuration_change",
            "title": "Revised plan",
            "understood_request": "Clean the staging config.",
            "open_questions": list(open_questions or []),
        })
        return {"content": body, "usage": {"prompt_tokens": 5, "completion_tokens": 7}}, runtimes[0], [{"status": "ok"}]

    return chat


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _item(db, *, project_id=None) -> WorkItem:
    key = f"OCX-ANSWER-{uuid.uuid4().hex[:8]}"
    item = WorkItem(project_id=project_id, source_type="jira", source_instance="answers", source_key=key,
                    title=f"Answer {key}", work_state="ready_for_plan", sync_state="imported")
    db.add(item)
    await db.flush()
    return item


async def _plan(db, item, actor, *, version, status="needs_clarification", questions=QUESTIONS) -> WorkChangePlan:
    plan = WorkChangePlan(work_item_id=item.id, version=version, status=status, title=f"v{version}",
                          open_questions_json=list(questions), created_by=actor.id)
    db.add(plan)
    await db.flush()
    return plan


def _answers(*pairs):
    return [{"question_index": index, "question": QUESTIONS[index], "answer": answer} for index, answer in pairs]


async def _answer(db, plan, actor, calls, *, expected=None, answers=None, **chat_options):
    return await service.answer_plan_clarifications(
        db,
        change_plan_id=plan.id,
        current_user=actor,
        expected_latest_version=plan.version if expected is None else expected,
        answers=answers if answers is not None else _answers((0, "Staging only."), (2, "  No flag.  ")),
        chat_func=_chat(calls, **chat_options),
        runtime_resolver_func=_resolver,
    )


async def _rows(db, item) -> tuple:
    plans = (
        await db.execute(
            select(WorkChangePlan.version, WorkChangePlan.status)
            .where(WorkChangePlan.work_item_id == item.id)
            .execution_options(populate_existing=True)
            .order_by(WorkChangePlan.version)
        )
    ).all()
    audits = (await db.execute(select(func.count(AuditLog.id)).where(AuditLog.resource_id == item.id))).scalar_one()
    return [tuple(row) for row in plans], audits
