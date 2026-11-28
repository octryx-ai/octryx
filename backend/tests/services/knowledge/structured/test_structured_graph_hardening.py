"""Structured graph hardening: bounded worker, safe search expansion, generic profile, guarded counts."""

from __future__ import annotations

import time

from app.models.project.knowledge_structured import KnowledgeStructuredBuild
from app.services.knowledge.structured import build_slice as build_slice_module
from app.services.knowledge.structured import similarity
from app.services.knowledge.structured.build import claim_next_build, request_build, sync_layers
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import SLICE_SECONDS, STATE_COMPLETED, STATE_RUNNING, TRIGGER_MANUAL
from app.services.knowledge.structured.layers import LayerSpec
from app.services.knowledge.structured.profile import structured_profile
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.structured.structured_graph_support import SERVER_MANUAL, seed_parsed_revision
from tests.services.knowledge.structured.test_structured_graph_similarity import (
    FakeVectors,
    _context,
    _key,
    _similar,
    _two_manuals,
)


async def _claimed_build(db, project_id: str, layers: list[str]) -> KnowledgeStructuredBuild:
    build = await request_build(db, project_id=project_id, layers=layers, trigger=TRIGGER_MANUAL)
    assert await claim_next_build(db, worker_id="w") == build.id
    return build


async def _until_done(db, build_id: str, **kwargs) -> str:
    state = STATE_RUNNING
    for _ in range(20):
        state = await run_build_slice(db, runtime=None, build_id=build_id, worker_id="w", **kwargs)
        if state != STATE_RUNNING:
            break
    return state


def test_a_slice_is_short_enough_for_the_projection_tick():
    assert SLICE_SECONDS <= 10.0


def test_a_source_sync_requests_only_the_layers_its_connector_kind_feeds():
    profile = structured_profile()
    assert sync_layers(profile, "git_repository") == ["configuration"]
    assert sync_layers(profile, "servicenow") == ["operations"] and sync_layers(profile, "jira") == ["operations"]
    assert sync_layers(profile, "confluence") == ["manual", "operations"]
    assert sync_layers(profile, None) == ["manual", "configuration", "operations"]


async def test_linkage_is_skipped_for_layers_the_build_did_not_change(db):
    project_id = await seed_workspace(db)
    await seed_parsed_revision(db, project_id, source_key="server", title="Server", spans=SERVER_MANUAL)
    first = await _claimed_build(db, project_id, ["manual", "configuration"])
    assert await _until_done(db, first.id) == STATE_COMPLETED
    await db.refresh(first)
    assert first.report["linkage"]["configuration"]["state"] == "ok"
    assert first.report["linkage"]["manual"] == {"state": "needs_configuration"}

    second = await _claimed_build(db, project_id, ["manual", "configuration"])
    assert await _until_done(db, second.id) == STATE_COMPLETED
    await db.refresh(second)
    layers = second.report["layers"]
    assert layers["manual"]["extracted"] == 0 and layers["manual"]["retired"] == 0
    assert second.report["linkage"]["configuration"] == {"state": "unchanged"}
    assert second.report["linkage"]["manual"] == {"state": "needs_configuration"}


async def test_linkage_waits_for_the_next_slice_when_the_deadline_has_passed_and_resumes_a_partial_step(
    db, monkeypatch
):
    project_id = await seed_workspace(db)
    calls: list[dict | None] = []

    async def select_none(context):
        return []

    async def link(context, *, deadline, progress):
        calls.append(progress)
        if progress is None:
            return {"state": "partial", "cursor": 1}
        return {"state": "ok", "resumed_from": progress["cursor"]}

    monkeypatch.setattr(build_slice_module, "layer_specs", lambda: {"manual": LayerSpec("manual", select_none, None, link)})
    build = await _claimed_build(db, project_id, ["manual"])
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w", budget_seconds=-1) == (
        STATE_RUNNING
    )
    assert calls == []
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w") == STATE_RUNNING
    assert await run_build_slice(db, runtime=None, build_id=build.id, worker_id="w") == STATE_COMPLETED
    await db.refresh(build)
    assert calls == [None, {"state": "partial", "cursor": 1}]
    assert build.report["linkage"]["manual"] == {"state": "ok", "resumed_from": 1}
    assert build.report["slices"] == 3


async def test_the_similarity_pass_advances_by_a_cursor_and_ends_like_a_single_pass(db, monkeypatch):
    project_id, server, app = await _two_manuals(db)
    neighbours = {
        _key(server, 8): [(_key(app, 3), 0.08)],
        _key(server, 1): [(_key(app, 1), 0.1)],
    }
    whole = await similarity.link_similar_sections(_context(db, project_id, FakeVectors(neighbours)))
    expected = sorted((edge.edge_key, edge.properties["score"]) for edge in await _similar(db, project_id))
    assert whole["state"] == "ok" and len(expected) == whole["edges"] >= 1

    monkeypatch.setattr(similarity, "MAX_SECTIONS_PER_STEP", 1)
    bounded = await similarity.link_similar_sections(_context(db, project_id, FakeVectors(neighbours)))
    assert bounded["state"] == "partial" and bounded["cursor"] == 1
    progress, steps = None, 0
    while True:
        result = await similarity.link_similar_sections(
            _context(db, project_id, FakeVectors(neighbours)), deadline=time.monotonic() - 1, progress=progress
        )
        steps += 1
        if result["state"] != "partial":
            break
        assert result["cursor"] == steps and "pass_started" in result
        progress = result
    assert result["state"] == "ok" and steps == result["sections"] and steps > 1
    assert sorted((edge.edge_key, edge.properties["score"]) for edge in await _similar(db, project_id)) == expected

    progress = None
    while True:
        result = await similarity.link_similar_sections(
            _context(db, project_id, FakeVectors({})), deadline=None, progress=progress
        )
        if result["state"] != "partial":
            break
        assert len(await _similar(db, project_id)) == len(expected)
        progress = result
    assert result["removed"] == len(expected) and not await _similar(db, project_id)
