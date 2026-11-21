"""The runner holds builds on a short renewed lease, resumes the build of a dead runner, and records claims, idle polls, missing runtimes and failures."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from app.models.project.knowledge_structured import KnowledgeStructuredBuild
from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
from app.services.knowledge.structured import build_runner
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_runner import StructuredBuildRunner
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import STATE_COMPLETED, STATE_FAILED, STATE_RUNNING, TRIGGER_MANUAL
from app.services.knowledge.structured.status import structured_status
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.structured_graph_build_runner_support import _factory, _reload, _runner, _workspace


async def _author(db, project_id):
    from app.services.knowledge.access.authorization import AuthorizedWorkspace, parse_workspace_id

    return AuthorizedWorkspace(workspace=parse_workspace_id(project_id), project_id=project_id, role="owner")


async def _run_state(db):
    from app.models import BackgroundWorkerRunState

    return await db.get(BackgroundWorkerRunState, build_runner.RUNNER_NAME, populate_existing=True)


async def test_the_runner_holds_a_build_on_a_short_lease_that_every_slice_renews(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    runner = _runner(db, max_run_seconds=0.0)
    assert await claim_next_build(db, worker_id=runner.worker_id, triggers=(TRIGGER_MANUAL,),
                                  lease_seconds=build_runner.LEASE_SECONDS) == build.id
    claimed = await _reload(db, build)
    assert claimed.lease_until <= utc_now() + timedelta(seconds=build_runner.LEASE_SECONDS + 1)
    renewed = await run_build_slice(db, runtime=build_runtime()[0], build_id=build.id, worker_id=runner.worker_id,
                                    max_revisions=1, lease_seconds=build_runner.LEASE_SECONDS)
    assert renewed == STATE_RUNNING
    slice_lease = (await _reload(db, build)).lease_until
    assert utc_now() < slice_lease <= utc_now() + timedelta(seconds=build_runner.LEASE_SECONDS + 1)
    assert build_runner.LEASE_SECONDS <= 60


async def test_a_build_of_a_runner_that_died_is_resumed_after_its_short_lease(db, monkeypatch):
    from app.services.knowledge.structured import build as build_module

    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    dead = _runner(db)
    # The old process claimed the build and ran one slice, then the process ended (no hand-back).
    assert await claim_next_build(db, worker_id=dead.worker_id, triggers=(TRIGGER_MANUAL,),
                                  lease_seconds=build_runner.LEASE_SECONDS) == build.id
    await run_build_slice(db, runtime=build_runtime()[0], build_id=build.id, worker_id=dead.worker_id,
                          max_revisions=1, lease_seconds=build_runner.LEASE_SECONDS)
    restarted = _runner(db)
    assert await restarted.run_once() is None  # the lease is still live
    later = utc_now() + timedelta(seconds=build_runner.LEASE_SECONDS + 1)
    monkeypatch.setattr(build_module, "utc_now", lambda: later)
    assert await restarted.run_once() == STATE_COMPLETED
    resumed = await _reload(db, build)
    assert resumed.claimed_by == restarted.worker_id and resumed.report["layers"]["manual"]["extracted"] == 2


async def test_status_marks_a_running_build_without_a_live_lease(db):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="structured-runner:gone", lease_seconds=30) == build.id
    authorized = await _author(db, project_id)
    assert (await structured_status(db, authorized=authorized))["builds"][0]["lease_expired"] is False
    await db.execute(update(KnowledgeStructuredBuild).where(KnowledgeStructuredBuild.id == build.id)
                     .values(lease_until=utc_now() - timedelta(seconds=1)))
    await db.commit()
    assert (await structured_status(db, authorized=authorized))["builds"][0]["lease_expired"] is True


async def test_the_runner_claims_and_renews_with_its_short_lease(db, monkeypatch):
    project_id = await _workspace(db)
    await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    leases: list[tuple[str, float]] = []
    real_claim, real_slice = build_runner.claim_next_build, build_runner.run_build_slice

    async def spy_claim(db, **kwargs):
        leases.append(("claim", kwargs.get("lease_seconds")))
        return await real_claim(db, **kwargs)

    async def spy_slice(db, **kwargs):
        leases.append(("slice", kwargs.get("lease_seconds")))
        return await real_slice(db, **kwargs)

    monkeypatch.setattr(build_runner, "claim_next_build", spy_claim)
    monkeypatch.setattr(build_runner, "run_build_slice", spy_slice)
    assert await _runner(db).run_once() == STATE_COMPLETED
    assert leases[0] == ("claim", build_runner.LEASE_SECONDS) and len(leases) >= 2
    assert all(lease == build_runner.LEASE_SECONDS for _, lease in leases)


async def test_the_runner_records_every_claim_and_throttles_idle_polls(db, monkeypatch):
    project_id = await _workspace(db)
    runner = _runner(db)
    assert await runner.run_once() is None  # idle: recorded once
    idle = await _run_state(db)
    assert idle.status == "success" and idle.run_count == 1 and idle.processed_count == 0
    assert await runner.run_once() is None  # idle again within the interval: not written
    assert (await _run_state(db)).run_count == 1
    await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    assert await runner.run_once() == STATE_COMPLETED
    claimed = await _run_state(db)
    assert claimed.run_count == 2 and claimed.processed_count >= 2
    assert claimed.details_json["counts"]["completed_count"] == 1 and claimed.owner == runner.worker_id
    authorized = await _author(db, project_id)
    runner_status = (await structured_status(db, authorized=authorized))["runner"]
    assert runner_status["status"] == "success" and runner_status["run_count"] == 2
    assert runner_status["failure"] is None and "owner" not in runner_status
    assert build_runner.RUNNER_NAME == "structured_build_runner"  # the admin worker list shows this name
    monkeypatch.setattr(build_runner, "HEALTH_INTERVAL_SECONDS", 0.0)
    assert await runner.run_once() is None
    assert (await _run_state(db)).run_count == 3


async def test_the_runner_records_a_missing_runtime_as_a_fixed_failure_token(db):
    project_id = await _workspace(db)

    def missing():
        raise EvidenceStoreNotConfiguredError("bolt://user:secret@graph")

    runner = StructuredBuildRunner(_factory(db), runtime_provider=missing)
    assert await runner.run_once() is None
    state = await _run_state(db)
    assert state.status == "failed" and state.error == build_runner.FAILURE_RUNTIME and state.failure_count == 1
    status = await structured_status(db, authorized=await _author(db, project_id))
    assert status["runner"]["failure"] == build_runner.FAILURE_RUNTIME and "secret" not in repr(status)
    assert await runner.run_once() is None  # the same outcome within the interval: not written again
    assert (await _run_state(db)).failure_count == 1


async def test_a_failed_build_and_a_broken_pass_are_recorded(db, monkeypatch):
    project_id = await _workspace(db)
    await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)

    async def broken(db, **kwargs):
        raise RuntimeError("postgres://user:secret@db")

    monkeypatch.setattr(build_runner, "run_build_slice", broken)
    runner = _runner(db, poll_interval_seconds=0.01)
    assert await runner.run_once() == STATE_FAILED
    assert (await _run_state(db)).details_json["counts"]["failed_count"] == 1

    async def outside_contract():
        runner._stop_event.set()
        raise RuntimeError("redis://user:secret@cache")

    monkeypatch.setattr(runner, "run_once", outside_contract)
    await runner._run_loop()
    state = await _run_state(db)
    assert state.status == "failed" and state.error == build_runner.FAILURE_PASS and "secret" not in str(state.error)
