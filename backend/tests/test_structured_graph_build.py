"""Structured graph builds over the real ledger: idempotent, incremental, bounded, profile-aware."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.project.knowledge_structured import (
    KnowledgeStructuredBuild,
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from app.services.knowledge.projection.worker import KnowledgeProjectionWorker
from app.services.knowledge.structured import build as build_module
from app.services.knowledge.structured import workspace_profile as workspace_profile_module
from app.services.knowledge.structured.build import (
    StructuredBuildRequestError,
    claim_next_build,
    request_build,
    run_next_build,
)
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import (
    RESULT_LOST,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    TRIGGER_MANUAL,
    TRIGGER_SOURCE_SYNC,
)
from app.services.knowledge.structured.facts import node_id
from app.services.knowledge.structured.profile import structured_profile
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.structured_graph_support import CONSOLE_MANUAL, SERVER_MANUAL, seed_parsed_revision

SERVER = "demo-shop-server-guide"
WORKER = "projection:test-structured"


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _run(db, project_id, *, layers=("manual",), max_revisions=100) -> KnowledgeStructuredBuild:
    build = await request_build(db, project_id=project_id, layers=list(layers), trigger=TRIGGER_MANUAL)
    claimed = await claim_next_build(db, worker_id=WORKER)
    assert claimed == build.id
    state = STATE_RUNNING
    for _ in range(20):
        state = await run_build_slice(db, runtime=None, build_id=build.id, worker_id=WORKER,
                                      max_revisions=max_revisions)
        if state != STATE_RUNNING:
            break
    assert state != STATE_RUNNING
    await db.refresh(build)
    return build


async def _count(db, model, **where) -> int:
    statement = select(func.count()).select_from(model)
    for name, value in where.items():
        statement = statement.where(getattr(model, name) == value)
    return int((await db.execute(statement)).scalar_one())


async def _workspace_with_server_manual(db):
    project_id = await seed_workspace(db)
    source_id, revision_id = await seed_parsed_revision(
        db, project_id, source_key=SERVER, title="Demo Shop Server Guide 1.4", spans=SERVER_MANUAL
    )
    return project_id, source_id, revision_id


async def test_a_manual_build_writes_cited_nodes_edges_ledger_and_report(db):
    project_id, _, revision_id = await _workspace_with_server_manual(db)
    build = await _run(db, project_id)
    assert build.state == STATE_COMPLETED and build.profile == "structured-v4"
    layer = build.report["layers"]["manual"]
    assert layer["selected"] == 1 and layer["extracted"] == 1 and layer["already_current"] == 0
    assert layer["nodes"] == await _count(db, KnowledgeStructuredNode, revision_id=revision_id) > 0
    assert build.report["linkage"]["manual"] == {"state": "needs_configuration"}
    lock = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.node_id == node_id("Parameter", f"{SERVER}|ini:Cache?|RequestTimeout")))).scalar_one()
    assert lock.span_ordinal == 9 and lock.layer == "manual" and lock.profile == "structured-v4"
    edge = (await db.execute(select(KnowledgeStructuredEdge).where(
        KnowledgeStructuredEdge.source_id == lock.node_id))).scalar_one()
    assert edge.edge_type == "documented_in" and edge.citations == [[revision_id, 9, None]]
    ledger = await db.get(KnowledgeStructuredExtraction, (revision_id, "structured-v4"))
    assert ledger.extractor == "manual-rules" and ledger.node_count == layer["nodes"]


async def test_rebuilding_an_unchanged_workspace_touches_nothing(db):
    project_id, _, revision_id = await _workspace_with_server_manual(db)
    await _run(db, project_id)
    ids = set((await db.execute(select(KnowledgeStructuredNode.id))).scalars())
    again = await _run(db, project_id)
    layer = again.report["layers"]["manual"]
    assert layer["extracted"] == 0 and layer["already_current"] == 1 and layer["retired"] == 0
    assert set((await db.execute(select(KnowledgeStructuredNode.id))).scalars()) == ids


async def test_a_new_revision_replaces_the_old_one_and_a_removed_source_retires(db):
    project_id, source_id, first = await _workspace_with_server_manual(db)
    await _run(db, project_id)
    changed = [*SERVER_MANUAL[:8], SERVER_MANUAL[8].__class__(
        9, "[Cache?] Parameter | Default | Description\nRequestTimeout | 30000 | Timeout in milliseconds.",
        "table", 125, 125, ("6.3.3 Cache Settings",))]
    _, second = await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual", spans=changed,
                                           source_id=source_id, revision_ordinal=2)
    build = await _run(db, project_id)
    layer = build.report["layers"]["manual"]
    assert layer["retired"] == 1 and layer["extracted"] == 1 and layer["removed_nodes"] > 0
    assert await _count(db, KnowledgeStructuredNode, revision_id=first) == 0
    lock = (await db.execute(select(KnowledgeStructuredNode).where(
        KnowledgeStructuredNode.revision_id == second,
        KnowledgeStructuredNode.node_id == node_id("Parameter", f"{SERVER}|ini:Cache?|RequestTimeout")))).scalar_one()
    assert lock.properties["default"] == "30000"
    # The source is removed: nothing current is selected, so everything it stated retires.
    from app.models.project.knowledge_evidence import KnowledgeSourceHead

    head = await db.get(KnowledgeSourceHead, source_id)
    head.current_revision_id = None
    await db.commit()
    build = await _run(db, project_id)
    assert build.report["layers"]["manual"]["retired"] == 1
    assert await _count(db, KnowledgeStructuredNode, project_id=project_id) == 0
    assert await _count(db, KnowledgeStructuredExtraction, project_id=project_id) == 0


async def test_a_new_profile_version_reextracts_without_touching_other_graphs(db, monkeypatch):
    project_id, _, revision_id = await _workspace_with_server_manual(db)
    await _run(db, project_id)
    newer = dataclasses.replace(structured_profile(), version=structured_profile().version + 1)
    monkeypatch.setattr(workspace_profile_module, "structured_profile", lambda: newer)
    build = await _run(db, project_id)
    layer = build.report["layers"]["manual"]
    assert layer["retired"] == 1 and layer["extracted"] == 1
    profiles = set((await db.execute(select(KnowledgeStructuredNode.profile))).scalars())
    assert profiles == {newer.profile_id}


async def test_a_build_runs_in_bounded_slices_and_continues_where_the_ledger_says(db):
    project_id, _, _ = await _workspace_with_server_manual(db)
    await seed_parsed_revision(db, project_id, source_key="demo-shop-console-guide",
                               title="Demo Shop Console", spans=CONSOLE_MANUAL)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id=WORKER) == build.id
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id=WORKER, max_revisions=1) == STATE_RUNNING
    await db.refresh(build)
    assert build.report["layers"]["manual"]["extracted"] == 1 and build.lease_until is not None
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id=WORKER, max_revisions=1) == (
        STATE_COMPLETED
    )
    await db.refresh(build)
    assert build.report["layers"]["manual"]["extracted"] == 2 and build.report["slices"] == 2


async def test_requests_merge_into_the_pending_build_and_bad_layers_are_refused(db):
    project_id = await seed_workspace(db)
    first = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    second = await request_build(db, project_id=project_id, layers=["operations"], trigger=TRIGGER_MANUAL)
    assert first.id == second.id and second.layers == ["manual", "operations"]
    for bad in ([], ["everything"], "manual", [1]):
        with pytest.raises(StructuredBuildRequestError):
            await request_build(db, project_id=project_id, layers=bad, trigger=TRIGGER_MANUAL)


async def test_only_one_build_per_workspace_runs_at_a_time(db):
    project_id = await seed_workspace(db)
    first = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id=WORKER) == first.id
    await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="projection:other") is None
    # Another worker's build: the slice reports it lost and writes nothing.
    assert await run_build_slice(db, runtime=None, build_id=first.id, worker_id="projection:other") == RESULT_LOST


async def test_a_failing_slice_fails_the_build_with_a_fixed_token(db, monkeypatch):
    project_id = await seed_workspace(db)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)

    async def broken(*args, **kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(build_module, "run_build_slice", broken)
    assert await run_next_build(_factory(db), runtime=None, worker_id=WORKER) == STATE_FAILED
    await db.refresh(build)
    assert build.state == STATE_FAILED and build.failure == "build_failed" and "secret" not in str(build.report)


async def test_the_projection_worker_tick_runs_a_due_source_sync_build_and_leaves_manual_builds_alone(db):
    project_id, _, _ = await _workspace_with_server_manual(db)
    other, _, _ = await _workspace_with_server_manual(db)
    manual = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    refresh = await request_build(db, project_id=other, layers=["manual"], trigger=TRIGGER_SOURCE_SYNC)
    runtime, _, _ = build_runtime()
    worker = KnowledgeProjectionWorker(_factory(db), runtime_provider=lambda: runtime, worker_id=WORKER)
    await worker.run_tick()
    await db.refresh(manual)
    await db.refresh(refresh)
    assert refresh.state == STATE_COMPLETED and refresh.report["layers"]["manual"]["extracted"] == 1
    # A manual build is the structured build runner's (test_structured_graph_build_runner.py).
    assert manual.state == "pending" and manual.claimed_by is None


async def test_replacing_a_revision_twice_never_duplicates_its_rows(db):
    from app.services.knowledge.structured.manual import extract_manual
    from app.services.knowledge.structured.store import replace_revision

    project_id, _, revision_id = await _workspace_with_server_manual(db)
    extraction = extract_manual(list(SERVER_MANUAL), structured_profile(), document_key=SERVER, title="x")
    for _ in range(2):
        counts = await replace_revision(db, project_id=project_id, revision_id=revision_id, layer="manual",
                                        profile_id="structured-v4", extractor="manual-rules", extraction=extraction)
        await db.commit()
    assert counts.removed_nodes == counts.nodes == len(extraction.nodes)
    assert await _count(db, KnowledgeStructuredNode, revision_id=revision_id) == len(extraction.nodes)
    assert await _count(db, KnowledgeStructuredEdge, revision_id=revision_id) == len(extraction.edges)
