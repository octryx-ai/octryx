"""On real PostgreSQL: the run claim is a row lock, and a step that works outside the run releases it.

Two real connections (``OCTRYX_TEST_LEDGER_POSTGRES_URL``: a disposable database migrated to head; skipped
without it — a pre-deploy PostgreSQL smoke step):

- while a step holds the claim, a second writer's claim waits on the row (visible in ``pg_locks``);
- after ``release_for_external_work`` the second writer claims at once and stops the run;
- the first step's ``resume_after_external_work`` then refuses (``run_moved_on``) and writes nothing.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import update

from app.models import WorkflowRun
from app.services.workflow_runs.external_step import release_for_external_work, resume_after_external_work
from app.services.workflow_runs.records import WorkflowRunError, lock_run
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.knowledge_retention_postgres_support import (
    UNGRANTED_ROW_WAIT,
    postgres_sessions,
    requires_postgres,
    until,
)

pytestmark = pytest.mark.asyncio


async def _seed_run(factory) -> str:
    async with factory() as session:
        workspace_id = await seed_workspace(session)
        user_id = await seed_member(session, workspace_id=workspace_id)
        run = WorkflowRun(workflow_kind="phased", workflow_key="afs4-claim", requested_by=user_id,
                          project_id=workspace_id, current_node_id="docs_in_knowledge",
                          node_state={"entry": 1}, context={})
        session.add(run)
        await session.commit()
        return run.id


@requires_postgres
async def test_a_released_step_lets_a_stop_in_and_then_records_nothing():
    engine, factory = postgres_sessions()
    try:
        run_id = await _seed_run(factory)
        async with factory() as step, factory() as rival, factory() as observer:
            run = await step.get(WorkflowRun, run_id)
            await lock_run(step, run)

            # Held: the rival's claim waits on the row.
            other = await rival.get(WorkflowRun, run_id)
            waiting = asyncio.create_task(lock_run(rival, other))
            await until(observer, UNGRANTED_ROW_WAIT, 1)
            assert not waiting.done()

            # Released explicitly: the rival gets the row, stops the run and commits.
            held = await release_for_external_work(step, run, key="docs_in_knowledge#1", facts={})
            await asyncio.wait_for(waiting, timeout=10)
            await rival.execute(update(WorkflowRun).where(WorkflowRun.id == run_id).values(status="stopped"))
            await rival.commit()

            with pytest.raises(WorkflowRunError) as moved:
                await resume_after_external_work(step, run, held, {})
            assert moved.value.code == "run_moved_on"
            await step.rollback()
    finally:
        await engine.dispose()
