"""Repository steps run after the request that reached them (``deferred_action``).

The start only marks ``scm.create_branch``; the executor runs it with its own lease, and the run goes on from its
result. A lost start or a dead executor is started again by the sweep; a run that moved on gets nothing written.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from app.services.workflow_runs import deferred_action
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.sweep import sweep_waiting_runs
from app.time_utils import utc_now
from tests.test_workflow_run_platform_actions import _definition, _item, _run

pytestmark = [pytest.mark.asyncio, pytest.mark.deferred_actions]


class Branches:
    def __init__(self, monkeypatch) -> None:
        self.calls = 0

        async def create_branch(db, run, params):
            self.calls += 1
            run.branch = "feature/PAY-1-totals"
            return read_outcome({"status": "created", "branch": run.branch})

        monkeypatch.setattr(scm, "create_branch", create_branch)


def _same_session(db):
    @asynccontextmanager
    async def factory():
        yield db

    return factory


async def _started(db, monkeypatch):
    branches = Branches(monkeypatch)
    scheduled: list[str] = []
    monkeypatch.setattr(deferred_action, "schedule", lambda run_id, **_: scheduled.append(run_id))
    item = await _item(db)
    run = await _run(db, _definition("scm.create_branch"), work_item_id=item.id, repository="github:acme/payments")
    await db.commit()
    return run, branches, scheduled


async def test_the_start_only_marks_the_step_and_the_executor_runs_it_after_the_commit(db, monkeypatch, tmp_path):
    run, branches, scheduled = await _started(db, monkeypatch)
    marker = run.context[deferred_action.MARKER_KEY]
    assert (branches.calls, run.status, run.current_node_id, marker["state"]) == (0, "running", "act", "pending")
    assert scheduled == [run.id]  # started once the request's transaction committed

    await deferred_action.execute(run.id, session_factory=_same_session(db))
    await db.refresh(run)
    assert (branches.calls, run.branch, run.outcome) == (1, "feature/PAY-1-totals", "done")
    assert deferred_action.MARKER_KEY not in run.context
    await deferred_action.execute(run.id, session_factory=_same_session(db))  # a second start: nothing to do
    assert branches.calls == 1


async def test_a_dead_executor_is_started_again_by_the_sweep_after_its_lease(db, monkeypatch, tmp_path):
    run, branches, scheduled = await _started(db, monkeypatch)
    token = await deferred_action._claim(db, run.id)  # an executor claimed it, then its process died
    await db.commit()
    assert token is not None and run.context[deferred_action.MARKER_KEY]["state"] == "started"
    scheduled.clear()
    await sweep_waiting_runs(db)
    assert scheduled == []  # the lease is live: never a second executor
    await sweep_waiting_runs(db, now=utc_now() + timedelta(seconds=deferred_action.LEASE_SECONDS + 1))
    assert scheduled == [run.id]


async def test_a_run_that_moved_on_gets_nothing_written(db, monkeypatch, tmp_path):
    run, branches, _ = await _started(db, monkeypatch)
    claimed = await deferred_action._claim(db, run.id)
    await db.commit()
    run.status = "aborted"  # a person aborted the run while the executor waited for the repository
    await db.commit()
    await deferred_action._run_step(db, run.id, claimed[0])
    assert (branches.calls, run.branch) == (0, None)


async def test_a_step_that_never_finishes_fails_after_its_attempts(db, monkeypatch, tmp_path):
    run, branches, _ = await _started(db, monkeypatch)
    for _ in range(deferred_action.MAX_ATTEMPTS + 1):
        marker = run.context[deferred_action.MARKER_KEY]
        run.context = {**run.context, deferred_action.MARKER_KEY: {**marker, "since": "2000-01-01T00:00:00"}}
        claimed = await deferred_action._claim(db, run.id)
        await db.commit()
    await deferred_action._run_step(db, run.id, claimed[0])
    await db.commit()
    assert (branches.calls, run.outcome) == (0, "blocked")  # the step's failed route
