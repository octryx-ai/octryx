"""Service tests for orchestrator agent runs."""

import pytest

from app.models.agent.orchestrator_agent import (
    ORCHESTRATOR_PATTERN_PARALLEL,
    ORCHESTRATOR_PATTERN_SEQUENTIAL,
    ORCHESTRATOR_PATTERN_SINGLE,
    ORCHESTRATOR_PATTERN_SUPERVISOR,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_RUNNING,
    ORCHESTRATOR_STATUS_WAITING_CHILDREN,
)
from app.services.orchestrator_service import (
    add_child_session,
    advance_sequential_step,
    create_orchestrator_run,
    get_orchestrator_run,
    get_orchestrator_runs_for_session,
    mark_orchestrator_waiting_children,
)


@pytest.mark.asyncio
async def test_create_orchestrator_run_single(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    assert run.id is not None
    assert run.pattern_type == ORCHESTRATOR_PATTERN_SINGLE
    assert run.status == ORCHESTRATOR_STATUS_RUNNING
    assert run.current_step_index == 0
    assert run.total_steps == 1


@pytest.mark.asyncio
async def test_create_orchestrator_run_supervisor(db):
    run = await create_orchestrator_run(
        db,
        session_id="s1",
        pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR,
        total_steps=3,
        max_iterations=5,
    )
    await db.commit()
    assert run.pattern_type == ORCHESTRATOR_PATTERN_SUPERVISOR
    assert run.total_steps == 3
    assert run.max_iterations == 5


@pytest.mark.asyncio
async def test_get_orchestrator_run(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    fetched = await get_orchestrator_run(db, run_id=run.id)
    assert fetched is not None
    assert fetched.id == run.id


@pytest.mark.asyncio
async def test_get_orchestrator_run_not_found(db):
    result = await get_orchestrator_run(db, run_id="nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_orchestrator_runs_for_session(db):
    await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SEQUENTIAL)
    await create_orchestrator_run(db, session_id="s2", pattern_type=ORCHESTRATOR_PATTERN_PARALLEL)
    await db.commit()

    runs_s1 = await get_orchestrator_runs_for_session(db, session_id="s1")
    assert len(runs_s1) == 2
    assert all(r.session_id == "s1" for r in runs_s1)

    runs_s1_seq = await get_orchestrator_runs_for_session(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SEQUENTIAL)
    assert len(runs_s1_seq) == 1


@pytest.mark.asyncio
async def test_add_child_session(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_PARALLEL)
    await db.commit()
    await add_child_session(db, run, "child-1")
    await add_child_session(db, run, "child-2")
    await add_child_session(db, run, "child-1")  # idempotent
    await db.commit()

    assert run.child_session_ids_json == ["child-1", "child-2"]
    assert run.last_child_id == "child-2"


@pytest.mark.asyncio
async def test_advance_sequential_step(db):
    run = await create_orchestrator_run(
        db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SEQUENTIAL, total_steps=3
    )
    await db.commit()

    await advance_sequential_step(db, run)
    await db.commit()
    assert run.current_step_index == 1
    assert run.status == ORCHESTRATOR_STATUS_RUNNING

    await advance_sequential_step(db, run)
    await db.commit()
    assert run.current_step_index == 2

    await advance_sequential_step(db, run)
    await db.commit()
    assert run.current_step_index == 3
    assert run.status == ORCHESTRATOR_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_advance_sequential_step_only_for_sequential(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    with pytest.raises(ValueError, match="only valid for sequential"):
        await advance_sequential_step(db, run)


@pytest.mark.asyncio
async def test_mark_waiting_children(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_PARALLEL)
    await db.commit()
    await mark_orchestrator_waiting_children(db, run)
    await db.commit()
    assert run.status == ORCHESTRATOR_STATUS_WAITING_CHILDREN
