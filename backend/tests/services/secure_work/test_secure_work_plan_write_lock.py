"""Contract: every Change Plan writer serializes on the same per-Work-Item lock."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.models import WorkChangePlan, WorkChangePlanDecision
from app.services.secure_work.plans import (
    change_plans,
    clarification_answers,
    llm_work_plan,
    plan_write_lock,
    redeclare,
)
from tests.secure_work_plan_clarification_answers_support import _admin, _answer, _item, _plan, _resolver
from tests.secure_work_plan_clarification_answers_support import _chat as fake_chat


def _spy(monkeypatch, db, locks):
    async def lock(session, work_item_id):
        pending = [row for row in (*session.new, *session.dirty) if isinstance(row, (WorkChangePlan, WorkChangePlanDecision))]
        assert pending == [], "a plan write happened before the plan write lock"
        locks.append(work_item_id)
        return await plan_write_lock.lock_work_item_for_plan_write(session, work_item_id)

    for module in (change_plans, llm_work_plan, clarification_answers, redeclare):
        monkeypatch.setattr(module, "lock_work_item_for_plan_write", lock)


@pytest.mark.parametrize("writer", ["deterministic", "llm", "answers", "decision", "redeclare"])
async def test_every_plan_writer_takes_the_common_lock_before_writing(db, monkeypatch, writer):
    actor = await _admin(db)
    item = await _item(db)
    source = await _plan(db, item, actor, version=1)
    await db.flush()
    locks: list[str] = []
    _spy(monkeypatch, db, locks)

    if writer == "deterministic":
        await change_plans.generate_change_plan(db, work_item_id=item.id, current_user=actor, payload={})
    elif writer == "llm":
        await llm_work_plan.generate_llm_work_plan(
            db, work_item_id=item.id, current_user=actor, payload={},
            chat_func=fake_chat([]), runtime_resolver_func=_resolver,
        )
    elif writer == "answers":
        await _answer(db, source, actor, [])
    elif writer == "decision":
        await change_plans.decide_change_plan(
            db, change_plan_id=source.id, current_user=actor, payload={"action": "reject", "reason": "No."}
        )
    else:
        await redeclare.redeclare_work_item(db, work_item_id=item.id, current_user=actor, payload={"reason": "PR declined"})

    assert locks == [item.id]


async def test_redeclare_records_the_stored_status_not_a_stale_session_copy(db):
    actor = await _admin(db)
    item = await _item(db)
    plan = await _plan(db, item, actor, version=1, status="ready_for_review")
    await db.execute(text("UPDATE work_change_plans SET status='approved' WHERE id=:id"), {"id": plan.id})
    assert plan.status == "ready_for_review", "the session copy is stale"

    result = await redeclare.redeclare_work_item(db, work_item_id=item.id, current_user=actor, payload={"reason": "PR declined"})

    assert result["superseded_plans"] == 1
    decision = (
        await db.execute(select(WorkChangePlanDecision).where(WorkChangePlanDecision.change_plan_id == plan.id))
    ).scalar_one()
    assert (decision.from_status, decision.to_status) == ("approved", "superseded")
