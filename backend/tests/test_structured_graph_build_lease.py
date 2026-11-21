"""A runner whose build another worker claimed stops at once and writes nothing."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import BackgroundWorkerRunState
from app.models.project.knowledge_structured import (
    KnowledgeStructuredBuild,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from app.services.knowledge.structured import build_runner, build_slice
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_runner import StructuredBuildRunner
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import RESULT_LOST, TRIGGER_MANUAL, BuildLease, BuildLeaseLostError
from app.services.knowledge.structured.facts import Extraction
from app.services.knowledge.structured.store import write_revision
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.structured_graph_support import CONSOLE_MANUAL, SERVER_MANUAL, seed_parsed_revision

OTHER = "structured-runner:other"


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _workspace(db) -> str:
    project_id = await seed_workspace(db)
    await seed_parsed_revision(db, project_id, source_key="server-manual", title="Server Manual", spans=SERVER_MANUAL)
    await seed_parsed_revision(db, project_id, source_key="console-guide", title="Console Guide",
                               spans=CONSOLE_MANUAL)
    return project_id


async def _take_over(db, build_id: str) -> None:
    await db.execute(update(KnowledgeStructuredBuild).where(KnowledgeStructuredBuild.id == build_id)
                     .values(claimed_by=OTHER, lease_until=utc_now() + timedelta(seconds=30)))
    await db.commit()


async def _count(db, model) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def test_a_runner_whose_build_another_worker_claimed_stops_at_once(db, monkeypatch):
    project_id = await _workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    runtime, _, _ = build_runtime()
    # A bounded run, so a regression (spinning on the lost build) fails instead of hanging.
    runner = StructuredBuildRunner(_factory(db), runtime_provider=lambda: runtime, max_run_seconds=3.0)
    slices: list[str] = []
    handed_back: list[str] = []
    sleeps: list[float] = []
    real_slice, real_sleep = build_runner.run_build_slice, asyncio.sleep

    async def spy_slice(session, **kwargs):
        state = await real_slice(session, **kwargs)
        slices.append(state)
        if len(slices) == 1:
            await _take_over(db, build.id)  # the runner stalled past its lease, another one claimed
        return state

    async def spy_hand_back(*args):
        handed_back.append("called")

    async def spy_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(build_runner, "run_build_slice", spy_slice)
    monkeypatch.setattr(build_runner, "hand_back", spy_hand_back)
    monkeypatch.setattr(build_runner.asyncio, "sleep", spy_sleep)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    assert await runner.run_once() == RESULT_LOST
    assert slices == ["running", RESULT_LOST] and sleeps == [build_runner.YIELD_SECONDS] and handed_back == []
    kept = await db.get(KnowledgeStructuredBuild, build.id, populate_existing=True)
    # The new owner's claim is untouched: its lease is not ended, nothing is reported as handed back.
    assert kept.claimed_by == OTHER and kept.state == "running"
    assert kept.lease_until.replace(tzinfo=None) > utc_now().replace(tzinfo=None)
    run_state = await db.get(BackgroundWorkerRunState, build_runner.RUNNER_NAME, populate_existing=True)
    counts = run_state.details_json["counts"]
    assert counts["lost_count"] == 1 and counts["handed_back_count"] == 0 and counts["completed_count"] == 0


async def test_a_slice_whose_claim_is_taken_mid_slice_rolls_its_write_back(db, monkeypatch):
    project_id = await _workspace(db)
    build_id = (await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)).id
    assert await claim_next_build(db, worker_id="structured-runner:old") == build_id
    real_profile = build_slice.workspace_profile

    async def taken_after_the_check(session, project):
        profile = await real_profile(session, project)
        await _take_over(session, build_id)  # between the slice's claim check and its first write
        return profile

    monkeypatch.setattr(build_slice, "workspace_profile", taken_after_the_check)
    state = await run_build_slice(db, runtime=None, build_id=build_id, worker_id="structured-runner:old")
    assert state == RESULT_LOST
    assert await _count(db, KnowledgeStructuredNode) == 0 and await _count(db, KnowledgeStructuredExtraction) == 0
    kept = await db.get(KnowledgeStructuredBuild, build_id, populate_existing=True)
    assert kept.claimed_by == OTHER and not (kept.report or {}).get("slices")


async def test_write_revision_checks_the_claim_inside_its_transaction(db):
    project_id = await seed_workspace(db)
    _, first = await seed_parsed_revision(db, project_id, source_key="one", title="One", spans=SERVER_MANUAL)
    _, second = await seed_parsed_revision(db, project_id, source_key="two", title="Two", spans=CONSOLE_MANUAL)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="structured-runner:old", lease_seconds=1) == build.id
    extraction = Extraction()
    extraction.node("Document", "doc", "Doc", None)
    kwargs = dict(project_id=project_id, revision_id=first, layer="manual", profile_id="structured-v4",
                  extractor="test", extraction=extraction)
    # Held (even with an expired lease nobody claimed): written, and the lease renewed.
    await db.execute(update(KnowledgeStructuredBuild).where(KnowledgeStructuredBuild.id == build.id)
                     .values(lease_until=utc_now() - timedelta(seconds=5)))
    await db.commit()
    _, complete = await write_revision(db, **kwargs, lease=BuildLease(build.id, "structured-runner:old", 30.0))
    await db.commit()
    renewed = await db.get(KnowledgeStructuredBuild, build.id, populate_existing=True)
    assert complete and renewed.lease_until.replace(tzinfo=None) > (utc_now() + timedelta(seconds=20)).replace(
        tzinfo=None)
    # Lost: refused before a row changes.
    await _take_over(db, build.id)
    with pytest.raises(BuildLeaseLostError):
        await write_revision(db, **{**kwargs, "revision_id": second},
                             lease=BuildLease(build.id, "structured-runner:old", 30.0))
    await db.rollback()
    revisions = set((await db.execute(select(KnowledgeStructuredExtraction.revision_id))).scalars())
    assert revisions == {first}


async def test_a_slice_whose_claim_is_taken_before_it_saves_reports_lost_and_completes_nothing(db, monkeypatch):
    project_id = await _workspace(db)
    build_id = (await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)).id
    assert await claim_next_build(db, worker_id="structured-runner:old") == build_id
    real_linkage = build_slice.run_linkage

    async def taken_during_linkage(context, **kwargs):
        done = await real_linkage(context, **kwargs)
        await _take_over(context.db, build_id)
        return done

    monkeypatch.setattr(build_slice, "run_linkage", taken_during_linkage)
    state = await run_build_slice(db, runtime=None, build_id=build_id, worker_id="structured-runner:old")
    assert state == RESULT_LOST
    kept = await db.get(KnowledgeStructuredBuild, build_id, populate_existing=True)
    assert kept.state == "running" and kept.claimed_by == OTHER and kept.finished_at is None
