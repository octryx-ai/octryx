"""Independent PostgreSQL concurrency acceptance for answer revisions.

Uses an explicitly supplied disposable PostgreSQL server and Alembic head. No
provider call: the model is paused at a barrier while actual service writers
commit, then the old answer must refuse. A second probe observes PostgreSQL's
blocking PID rather than treating a compiled FOR UPDATE statement as proof.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import User, WorkChangePlan, WorkItem
from app.services.secure_work.plans.change_plans import decide_change_plan, generate_change_plan
from app.services.secure_work.plans.clarification_answers import answer_plan_clarifications
from app.services.secure_work.plans.llm_work_plan import generate_llm_work_plan
from app.services.secure_work.plans.plan_write_lock import lock_work_item_for_plan_write
from app.services.secure_work.plans.redeclare import redeclare_work_item
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres


async def _runtime(_db, *, runtime_target_id=None):
    return [{"target_id": "test", "provider_id": "test", "provider_name": "bedrock", "model": "test"}]


async def _model(runtimes, **kwargs):
    assert kwargs["tools"] is None
    return {"content": json.dumps({"title": "Revised", "plan_type": "analysis", "open_questions": []})}, runtimes[0], []


async def _seed(maker):
    async with maker() as db:
        suffix = uuid.uuid4().hex
        actor = User(username=f"judge-{suffix}", email=f"{suffix}@example.invalid", password_hash="not-a-login")
        db.add(actor)
        await db.flush()
        item = WorkItem(source_type="manual", source_instance="pg-judge", source_key=suffix, title="Concurrency probe")
        db.add(item)
        await db.flush()
        plan = WorkChangePlan(work_item_id=item.id, version=1, status="needs_clarification", title="Source",
                              open_questions_json=["Which environment?"], created_by=actor.id)
        db.add(plan)
        await db.commit()
        return actor.id, item.id, plan.id


async def _answer(db, actor, plan_id, chat):
    return await answer_plan_clarifications(
        db, change_plan_id=plan_id, current_user=actor, expected_latest_version=1,
        answers=[{"question_index": 0, "question": "Which environment?", "answer": "Local test only"}],
        chat_func=chat, runtime_resolver_func=_runtime,
    )


async def _competing_writers(url):
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for writer in ("deterministic", "llm", "decision", "redeclare"):
            actor_id, item_id, plan_id = await _seed(maker)
            entered, release = asyncio.Event(), asyncio.Event()

            async def paused_model(runtimes, **kwargs):
                entered.set()
                await asyncio.wait_for(release.wait(), 15)
                return await _model(runtimes, **kwargs)

            async def pending_answer():
                async with maker() as db:
                    actor = await db.get(User, actor_id)
                    try:
                        await _answer(db, actor, plan_id, paused_model)
                        await db.commit()
                        return "unexpected_success"
                    except HTTPException as exc:
                        await db.rollback()
                        return exc.status_code, exc.detail

            task = asyncio.create_task(pending_answer())
            try:
                await asyncio.wait_for(entered.wait(), 15)
                async with maker() as db:
                    actor = await db.get(User, actor_id)
                    if writer == "deterministic":
                        await asyncio.wait_for(generate_change_plan(
                            db, work_item_id=item_id, current_user=actor, payload={}), 10)
                    elif writer == "llm":
                        await asyncio.wait_for(generate_llm_work_plan(
                            db, work_item_id=item_id, current_user=actor, payload={},
                            chat_func=_model, runtime_resolver_func=_runtime), 10)
                    elif writer == "decision":
                        await asyncio.wait_for(decide_change_plan(
                            db, change_plan_id=plan_id, current_user=actor,
                            payload={"action": "reject", "reason": "Concurrent rejection"}), 10)
                    else:
                        await asyncio.wait_for(redeclare_work_item(
                            db, work_item_id=item_id, current_user=actor,
                            payload={"reason": "Concurrent redeclaration"}), 10)
                    # This commits before the first model returns: no row lock across dispatch.
                    await db.commit()
                release.set()
                result = await asyncio.wait_for(task, 15)
                assert result[0] == 409, (writer, result)
                assert "plan_changed_during_generation" in result[1], (writer, result)
                async with maker() as db:
                    rows = (await db.execute(select(WorkChangePlan).where(WorkChangePlan.work_item_id == item_id))).scalars().all()
                    assert len(rows) == (2 if writer in {"deterministic", "llm"} else 1)
                    assert all("clarification" not in (row.evidence_json or {}) for row in rows)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


async def _observe_real_row_lock(url):
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        actor_id, item_id, plan_id = await _seed(maker)
        async with maker() as holder, maker() as contender, maker() as observer:
            actor = await contender.get(User, actor_id)
            # Preload stale identity-map state before the other transaction changes it.
            await contender.get(WorkChangePlan, plan_id)
            contender_pid = (await contender.execute(text("select pg_backend_pid()"))).scalar_one()
            holder_pid = (await holder.execute(text("select pg_backend_pid()"))).scalar_one()
            await lock_work_item_for_plan_write(holder, item_id)
            task = asyncio.create_task(_answer(contender, actor, plan_id, _model))
            try:
                async def blocked_by_holder():
                    while True:
                        blockers = (await observer.execute(text("select pg_blocking_pids(:pid)"), {"pid": contender_pid})).scalar_one()
                        if holder_pid in blockers:
                            return
                        assert not task.done(), "Answer did not wait for the real Work Item row lock"
                        await asyncio.sleep(0.02)

                await asyncio.wait_for(blocked_by_holder(), 15)
                plan = await holder.get(WorkChangePlan, plan_id)
                plan.status = "rejected"
                await holder.commit()
                try:
                    await asyncio.wait_for(task, 15)
                    raise AssertionError("Stale answer was accepted after acquiring the lock")
                except HTTPException as exc:
                    assert exc.status_code == 409
                await contender.rollback()
                rows = (await observer.execute(select(WorkChangePlan).where(WorkChangePlan.work_item_id == item_id))).scalars().all()
                assert [(row.version, row.status) for row in rows] == [(1, "rejected")]
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


def test_other_plan_writers_win_while_model_is_pending(tmp_path):
    with migrated_database("postgresql", tmp_path) as database:
        asyncio.run(_competing_writers(database.url))


def test_postgresql_blocks_then_refreshes_stale_answer_state(tmp_path):
    with migrated_database("postgresql", tmp_path) as database:
        asyncio.run(_observe_real_row_lock(database.url))
