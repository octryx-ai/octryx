"""A manual request takes over a running refresh: merges never change a build claimed later, a slice in flight hands the build back, and a slice that lost its lease writes nothing."""

from __future__ import annotations

from sqlalchemy import select, update

from app.models.project.knowledge_structured import KnowledgeStructuredBuild
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    TRIGGER_MANUAL,
    TRIGGER_SOURCE_SYNC,
)
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.structured_graph_build_runner_support import _factory, _reload, _runner, _workspace


async def test_a_merge_never_changes_a_build_claimed_after_it_was_read(db, monkeypatch):
    from app.services.knowledge.structured import build as build_module

    project_id = await _workspace(db)
    first = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_SOURCE_SYNC)
    real_target = build_module._merge_target
    claimed: list[str] = []

    async def target_then_claim(db, project_id, trigger):
        found = await real_target(db, project_id, trigger)
        if found is not None and not claimed:
            # A runner claims the pending build between the request's read and its UPDATE.
            claimed.append(await build_module.claim_next_build(db, worker_id="projection:race"))
        return found

    monkeypatch.setattr(build_module, "_merge_target", target_then_claim)
    second = await request_build(db, project_id=project_id, layers=["operations"], trigger=TRIGGER_SOURCE_SYNC)
    first = await _reload(db, first)
    assert claimed == [first.id] and first.state == STATE_RUNNING and first.layers == ["manual"]
    assert second.id != first.id and second.state == "pending" and second.layers == ["operations"]


async def test_a_manual_request_takes_over_a_running_refresh_and_the_runner_claims_it_at_once(db, monkeypatch):
    from app.services.knowledge.structured import build as build_module

    project_id = await _workspace(db)
    refresh = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_SOURCE_SYNC)
    runtime, _, _ = build_runtime()
    real_slice = build_module.run_build_slice

    async def one_revision(db, **kwargs):
        return await real_slice(db, **{**kwargs, "max_revisions": 1})

    monkeypatch.setattr(build_module, "run_build_slice", one_revision)
    # The projection worker runs one slice of the refresh and never holds the lease between ticks.
    state = await build_module.run_next_build(
        _factory(db), runtime=runtime, worker_id="projection:tick", triggers=build_module.COOPERATIVE_TRIGGERS
    )
    held = await _reload(db, refresh)
    assert state == STATE_RUNNING and held.state == STATE_RUNNING
    assert held.lease_until <= utc_now().replace(tzinfo=held.lease_until.tzinfo)
    manual = await request_build(db, project_id=project_id, layers=["configuration"], trigger=TRIGGER_MANUAL)
    assert manual.id == refresh.id and manual.trigger == TRIGGER_MANUAL
    assert manual.layers == ["manual", "configuration"]
    queued = await db.execute(select(KnowledgeStructuredBuild.id).where(KnowledgeStructuredBuild.state == "pending"))
    assert queued.first() is None  # nothing waits behind the refresh
    assert await _runner(db).run_once() == STATE_COMPLETED
    done = await _reload(db, refresh)
    assert done.report["layers"]["manual"]["extracted"] == 2 and "configuration" in done.report["layers"]


async def test_a_slice_in_flight_during_a_takeover_hands_the_build_back_instead_of_completing_it(db, monkeypatch):
    from app.services.knowledge.structured import build_slice, config_linkage

    project_id = await _workspace(db)
    refresh = await request_build(db, project_id=project_id, layers=["configuration"], trigger=TRIGGER_SOURCE_SYNC)
    assert await claim_next_build(db, worker_id="projection:tick") == refresh.id
    real_linkage, real_link_configuration = build_slice.run_linkage, config_linkage.link_configuration
    linked: list[str] = []

    async def link_then_takeover(context, **kwargs):
        # The manual request lands after the cooperative slice linked, just before it would complete.
        done = await real_linkage(context, **kwargs)
        await request_build(context.db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
        return done

    async def counted(context):
        linked.append(context.project_id)
        return await real_link_configuration(context)

    monkeypatch.setattr(build_slice, "run_linkage", link_then_takeover)
    monkeypatch.setattr(config_linkage, "link_configuration", counted)
    runtime, _, _ = build_runtime()
    state = await run_build_slice(db, runtime=runtime, build_id=refresh.id, worker_id="projection:tick")
    handed = await _reload(db, refresh)
    assert state == STATE_RUNNING and handed.state == STATE_RUNNING and handed.trigger == TRIGGER_MANUAL
    assert handed.layers == ["manual", "configuration"] and handed.finished_at is None
    assert handed.lease_until <= utc_now().replace(tzinfo=handed.lease_until.tzinfo)
    assert len(linked) == 1
    monkeypatch.setattr(build_slice, "run_linkage", real_linkage)
    assert await _runner(db).run_once() == STATE_COMPLETED
    done = await _reload(db, refresh)
    assert done.report["layers"]["manual"]["extracted"] == 2
    # The added manual layer changes what settings link to: the configuration linkage ran again.
    assert len(linked) == 2 and "configuration" in done.report["linkage"]


async def test_a_slice_that_lost_its_lease_writes_nothing_and_never_fails_the_new_owner(db):
    from app.services.knowledge.structured.build import fail_build

    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="structured-runner:old") == build.id
    await db.execute(update(KnowledgeStructuredBuild).where(KnowledgeStructuredBuild.id == build.id)
                     .values(claimed_by="structured-runner:new"))
    await db.commit()
    assert await fail_build(db, build.id, "structured-runner:old") == STATE_FAILED
    kept = await _reload(db, build)
    assert kept.state == STATE_RUNNING and kept.claimed_by == "structured-runner:new" and kept.failure is None


async def test_a_merge_overwritten_by_a_concurrent_merge_is_merged_again(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_SOURCE_SYNC)
    real_commit = db.commit
    overwritten: list[bool] = []

    async def commit_then_concurrent_write():
        await real_commit()
        if not overwritten:
            # Another request read the same pending build and writes its own list right after ours.
            overwritten.append(True)
            await db.execute(update(KnowledgeStructuredBuild).where(KnowledgeStructuredBuild.id == build.id)
                             .values(layers=["manual", "configuration"]))
            await real_commit()

    monkeypatch.setattr(db, "commit", commit_then_concurrent_write)
    merged = await request_build(db, project_id=project_id, layers=["operations"], trigger=TRIGGER_SOURCE_SYNC)
    assert overwritten and merged.id == build.id
    assert merged.layers == ["manual", "configuration", "operations"]
