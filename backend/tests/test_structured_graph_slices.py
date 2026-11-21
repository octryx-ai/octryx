"""Slice budget inside a revision write, and one plan per claim."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.project.knowledge_structured import (
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from app.services.knowledge.structured import build_runner, build_slice, store, store_revisions
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_runner import StructuredBuildRunner
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import STATE_COMPLETED, STATE_RUNNING, TRIGGER_MANUAL
from app.services.knowledge.structured.manual import extract_manual
from app.services.knowledge.structured.profile import structured_profile
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.structured_graph_support import CONSOLE_MANUAL, SERVER_MANUAL, seed_parsed_revision

SERVER = "server-manual"
WORKER = "structured-runner:test-slices"


async def _count(db, model, **where) -> int:
    statement = select(func.count()).select_from(model)
    for name, value in where.items():
        statement = statement.where(getattr(model, name) == value)
    return int((await db.execute(statement)).scalar_one())


def _always_past_deadline(monkeypatch) -> None:
    # Every batch after the first finds the deadline passed: one insert batch per slice.
    monkeypatch.setattr(store, "time", SimpleNamespace(monotonic=lambda: float("inf")))
    monkeypatch.setattr(store, "INSERT_BATCH", 5)


async def _slices_until_done(db, build_id: str, limit: int = 400) -> int:
    for count in range(1, limit):
        state = await run_build_slice(db, runtime=None, build_id=build_id, worker_id=WORKER)
        if state != STATE_RUNNING:
            assert state == STATE_COMPLETED
            return count
    raise AssertionError("the build never completed")


async def test_a_revision_larger_than_a_slice_is_written_over_several_slices_without_loss_or_duplicates(
    db, monkeypatch
):
    project_id = await seed_workspace(db)
    _, revision_id = await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual", spans=SERVER_MANUAL)
    expected = extract_manual(list(SERVER_MANUAL), structured_profile(), document_key=SERVER, title="Manual")
    _always_past_deadline(monkeypatch)
    real_specs = build_slice.layer_specs

    def probed_specs():
        specs = real_specs()
        manual = specs["manual"]

        async def extract(context, candidate):
            extractor, extraction = await manual.extract(context, candidate)
            extraction.warn("probe")
            return extractor, extraction

        specs["manual"] = dataclasses.replace(manual, extract=extract)
        return specs

    monkeypatch.setattr(build_slice, "layer_specs", probed_specs)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id=WORKER) == build.id
    # The first slice writes one batch and stops partial: rows, but no ledger row yet.
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id=WORKER) == STATE_RUNNING
    assert await _count(db, KnowledgeStructuredNode, revision_id=revision_id) == 5
    assert await _count(db, KnowledgeStructuredExtraction, revision_id=revision_id) == 0
    slices = 1 + await _slices_until_done(db, build.id)
    rows = len(expected.nodes) + len(expected.edges)
    assert slices >= rows // 5
    await db.refresh(build)
    layer = build.report["layers"]["manual"]
    assert layer["extracted"] == 1 and layer["partial_writes"] == slices - 1
    assert layer["nodes"] == len(expected.nodes) and layer["edges"] == len(expected.edges)
    assert await _count(db, KnowledgeStructuredNode, revision_id=revision_id) == len(expected.nodes)
    assert await _count(db, KnowledgeStructuredEdge, revision_id=revision_id) == len(expected.edges)
    ledger = await db.get(KnowledgeStructuredExtraction, (revision_id, structured_profile().profile_id))
    assert ledger.node_count == len(expected.nodes) and ledger.edge_count == len(expected.edges)
    # Warnings of a revision count once, however many slices wrote it.
    assert layer["warnings"] == dict(sorted({**expected.warnings, "probe": 1}.items()))
    assert await store_revisions.partial_revisions(db, project_id=project_id, layer="manual",
                                         profile_id=structured_profile().profile_id) == set()


async def test_a_resumed_write_drops_rows_the_extraction_no_longer_states(db):
    project_id = await seed_workspace(db)
    _, revision_id = await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual", spans=SERVER_MANUAL)
    full = extract_manual(list(SERVER_MANUAL), structured_profile(), document_key=SERVER, title="Manual")
    smaller = extract_manual(list(SERVER_MANUAL[:6]), structured_profile(), document_key=SERVER, title="Manual")
    common = dict(project_id=project_id, revision_id=revision_id, layer="manual", profile_id="structured-v4",
                  extractor="manual-rules")
    _, complete = await store.write_revision(db, **common, extraction=full, deadline=float("-inf"))
    assert not complete
    counts, complete = await store.write_revision(db, **common, extraction=smaller, resume=True)
    await db.commit()
    assert complete
    keys = set((await db.execute(select(KnowledgeStructuredNode.node_key)
                                 .where(KnowledgeStructuredNode.revision_id == revision_id))).scalars())
    assert keys == {ref.node_key for ref in smaller.nodes}
    assert await _count(db, KnowledgeStructuredEdge, revision_id=revision_id) == len(smaller.edges)


async def test_a_partial_revision_that_is_no_longer_current_is_retired(db, monkeypatch):
    project_id = await seed_workspace(db)
    source_id, first = await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual",
                                                  spans=SERVER_MANUAL)
    _always_past_deadline(monkeypatch)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id=WORKER) == build.id
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id=WORKER) == STATE_RUNNING
    assert await _count(db, KnowledgeStructuredNode, revision_id=first) == 5
    assert await store_revisions.partial_revisions(db, project_id=project_id, layer="manual",
                                         profile_id=structured_profile().profile_id) == {first}
    _, second = await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual",
                                           spans=SERVER_MANUAL[:6], source_id=source_id, revision_ordinal=2)
    monkeypatch.setattr(store, "INSERT_BATCH", 500)
    await _slices_until_done(db, build.id)
    assert await _count(db, KnowledgeStructuredNode, revision_id=first) == 0
    assert await _count(db, KnowledgeStructuredExtraction, revision_id=second) == 1
    await db.refresh(build)
    assert build.report["layers"]["manual"]["retired"] == 1


async def test_the_runner_plans_each_layer_once_per_claim_and_follows_the_ledger(db, monkeypatch):
    project_id = await seed_workspace(db)
    await seed_parsed_revision(db, project_id, source_key=SERVER, title="Manual", spans=SERVER_MANUAL)
    await seed_parsed_revision(db, project_id, source_key="console", title="App", spans=CONSOLE_MANUAL)
    build = await request_build(db, project_id=project_id, layers=["manual"], trigger=TRIGGER_MANUAL)
    plans: list[str] = []
    real_plan = build_slice._plan

    async def counted(context, spec, layer, entry):
        plans.append(layer)
        return await real_plan(context, spec, layer, entry)

    monkeypatch.setattr(build_slice, "_plan", counted)
    monkeypatch.setattr(build_runner, "MAX_REVISIONS_PER_SLICE", 1)
    runtime, _, _ = build_runtime()
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    assert await StructuredBuildRunner(factory, runtime_provider=lambda: runtime).run_once() == STATE_COMPLETED
    await db.refresh(build)
    assert build.report["slices"] >= 2 and plans == ["manual"]
    assert build.report["layers"]["manual"]["extracted"] == 2
    # Without a cache (the projection worker's single slice) each slice plans afresh.
    other = await seed_workspace(db)
    await seed_parsed_revision(db, other, source_key=SERVER, title="Manual", spans=SERVER_MANUAL)
    await seed_parsed_revision(db, other, source_key="console", title="App", spans=CONSOLE_MANUAL)
    second = await request_build(db, project_id=other, layers=["manual"], trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id=WORKER) == second.id
    plans.clear()
    while await run_build_slice(db, runtime=None, build_id=second.id, worker_id=WORKER, max_revisions=1) == (
        STATE_RUNNING
    ):
        pass
    assert len(plans) >= 2
