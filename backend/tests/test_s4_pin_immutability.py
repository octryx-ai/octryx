"""S4.2: a published composite never changes when its fragment does (contract §3.6, D-S4-1).

A composite pins a fragment version by id + canonical checksum and stores the compiled graph. A new fragment
version gets a new checksum and cannot satisfy the old pin; an unpublished fragment version blocks new drafts and
publishes that pin it, never a published composite; a tampered compiled graph is refused at publish. The
concurrency cases run on SQLite and, with ``OCTRYX_TEST_POSTGRES_URL``, really concurrently on PostgreSQL.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import FlowDefinitionVersion, User
from app.services.flow_capabilities import unpublish_flow_definition_version
from app.services.flow_draft_service import save_flow_draft
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.alembic_model_parity_support import DIALECTS, migrated_database
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.s4_fragment_support import (
    checksum,
    create,
    digest,
    make_admin,
    new_fragment_version,
    probe_composite,
    probe_fragment,
    publish,
    published_fragment,
    unique_key,
    version_row,
)


def _codes(error: HTTPException) -> set[str]:
    return {item["code"] for item in error.detail["errors"]}


async def _published_composite(db, author, reviewer):
    key, fragment_flow_id, v1_id, v1_pin = await published_fragment(db, author, reviewer)
    composite_key = unique_key("s4-probe")
    created = await create(db, author, composite_key, probe_composite(key, v1_id, v1_pin))
    composite_version_id = created["versions"][0]["id"]
    await publish(db, composite_version_id, reviewer)  # D2b2: a second admin publishes every phased version
    return key, fragment_flow_id, v1_id, v1_pin, composite_key, created["id"], composite_version_id


@pytest.mark.asyncio
async def test_a_new_fragment_version_never_changes_a_published_composite(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, fragment_flow_id, v1_id, v1_pin, composite_key, _flow_id, composite_version_id = (
        await _published_composite(db, author, reviewer))
    before = copy.deepcopy((await version_row(db, composite_version_id)).definition_json)

    v2 = probe_fragment(label="Go on, version two?")
    v2_id = await new_fragment_version(db, fragment_flow_id, v1_id, author, reviewer, v2, name=key)
    assert checksum(v2) != v1_pin

    row = await version_row(db, composite_version_id)
    assert row.status == "published"
    assert digest(row.definition_json) == digest(before)
    assert next(node for node in row.definition_json["nodes"] if node["id"] == "probe.confirm")["label"] == "Go on?"

    # A run started after v2 runs the composite version that pins v1.
    workspace_id = await seed_workspace(db)
    run = await start_run(db, user=author, workflow_key=composite_key, project_id=workspace_id,
                          session=await new_chat_session(db, author, workspace_id))
    assert run.flow_definition_version_id == composite_version_id and run.current_node_id == "probe.confirm"
    provenance = (await version_row(db, run.flow_definition_version_id)).runtime_settings["composition"]["provenance"]
    assert provenance["probe.confirm"]["version"] == 1 and provenance["probe.confirm"]["version_id"] == v1_id
    assert provenance["probe.confirm"]["version_id"] != v2_id

    # Upgrading is an explicit re-pin (D-S4-1): a draft pinned to v2 compiles v2's content.
    saved = await save_flow_draft(db, flow_id=_flow_id, current_user=author, payload={
        "expected_latest_version_id": composite_version_id, "definition": probe_composite(key, v2_id, checksum(v2)),
        "name": composite_key})
    draft = max(saved["versions"], key=lambda item: item["version"])
    assert draft["runtime_settings"]["composition"]["fragments"][0]["version"] == 2
    assert next(node for node in draft["definition"]["nodes"] if node["id"] == "probe.confirm")["label"] == (
        "Go on, version two?")


@pytest.mark.asyncio
async def test_an_unpinned_or_mismatched_pin_is_refused(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, fragment_flow_id, v1_id, v1_pin = await published_fragment(db, author, reviewer)
    v2 = probe_fragment(label="Changed")
    v2_id = await new_fragment_version(db, fragment_flow_id, v1_id, author, reviewer, v2, name=key)

    cases = {
        "fragment_pin_changed": probe_composite(key, v1_id, checksum(v2)),   # v1's id with v2's checksum
        "fragment_pin_changed ": probe_composite(key, v2_id, v1_pin),        # v2's id with v1's checksum
        "fragment_pin_unresolved": probe_composite(key, None, v1_pin),       # the API path needs the version id
        "fragment_pin_unresolved ": probe_composite(key, str(uuid.uuid4()), v1_pin),
        "fragment_pin_unresolved  ": probe_composite("another-key", v1_id, v1_pin),
    }
    for expected, source in cases.items():
        with pytest.raises(HTTPException) as refused:
            await create(db, author, unique_key("s4-probe"), source)
        assert refused.value.status_code == 422
        assert expected.strip() in _codes(refused.value), (expected, refused.value.detail)

    # A pin without a checksum is no pin at all.
    unpinned = probe_composite(key, v1_id, v1_pin)
    del unpinned["nodes"][1]["config"]["fragment_checksum"]
    with pytest.raises(HTTPException) as refused:
        await create(db, author, unique_key("s4-probe"), unpinned)
    assert refused.value.status_code == 422
    assert any(code.startswith("fragment_") for code in _codes(refused.value))


@pytest.mark.asyncio
async def test_a_fragment_of_another_workspace_is_out_of_scope(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    other = await seed_workspace(db)
    key = unique_key("s4-probe-confirm")
    created = await create(db, author, key, probe_fragment(), project_id=other)
    await publish(db, created["versions"][0]["id"], reviewer)
    with pytest.raises(HTTPException) as refused:
        await create(db, author, unique_key("s4-probe"),
                     probe_composite(key, created["versions"][0]["id"], checksum(probe_fragment())))
    assert "fragment_scope" in _codes(refused.value)


@pytest.mark.asyncio
async def test_an_unpublished_fragment_blocks_new_drafts_but_never_a_published_composite(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _fragment_flow_id, v1_id, v1_pin, composite_key, flow_id, composite_version_id = (
        await _published_composite(db, author, reviewer))
    await unpublish_flow_definition_version(db, version_id=v1_id, current_user=reviewer)

    with pytest.raises(HTTPException) as refused:
        await save_flow_draft(db, flow_id=flow_id, current_user=author, payload={
            "expected_latest_version_id": composite_version_id, "definition": probe_composite(key, v1_id, v1_pin),
            "name": composite_key})
    assert refused.value.status_code == 422 and "fragment_not_published" in _codes(refused.value)

    workspace_id = await seed_workspace(db)
    run = await start_run(db, user=author, workflow_key=composite_key, project_id=workspace_id,
                          session=await new_chat_session(db, author, workspace_id))
    assert run.flow_definition_version_id == composite_version_id and run.status == "waiting"


@pytest.mark.asyncio
async def test_a_draft_whose_pinned_fragment_was_unpublished_does_not_publish(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _fragment_flow_id, v1_id, v1_pin = await published_fragment(db, author, reviewer)
    created = await create(db, author, unique_key("s4-probe"), probe_composite(key, v1_id, v1_pin))
    await unpublish_flow_definition_version(db, version_id=v1_id, current_user=reviewer)
    with pytest.raises(HTTPException) as refused:
        await publish(db, created["versions"][0]["id"], reviewer)
    assert refused.value.status_code == 422 and "fragment_not_published" in _codes(refused.value)


@pytest.mark.asyncio
async def test_a_tampered_compiled_graph_is_refused_at_publish(db):
    author, reviewer = await make_admin(db), await make_admin(db)
    key, _fragment_flow_id, v1_id, v1_pin = await published_fragment(db, author, reviewer)
    created = await create(db, author, unique_key("s4-probe"), probe_composite(key, v1_id, v1_pin))
    version_id = created["versions"][0]["id"]
    tampered = copy.deepcopy(created["versions"][0]["definition"])
    next(node for node in tampered["nodes"] if node["id"] == "probe.confirm")["label"] = "Not what was pinned"
    await db.execute(update(FlowDefinitionVersion).where(FlowDefinitionVersion.id == version_id)
                     .values(definition_json=tampered))
    await db.flush()

    with pytest.raises(HTTPException) as refused:
        await publish(db, version_id, reviewer)
    assert refused.value.status_code == 422
    assert "fragment_composition_drift" in _codes(refused.value)
    row = await version_row(db, version_id)
    assert row.status == "draft"


# --- concurrency (SQLite sequentially, PostgreSQL concurrently) ------------------------------------------------


async def _users(maker) -> tuple[str, str]:
    async with maker() as db:
        author, reviewer = (User(id=str(uuid.uuid4()), username=f"s4-{uuid.uuid4().hex[:8]}",
                                 email=f"s4-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", is_active=True)
                            for _ in range(2))
        db.add_all([author, reviewer])
        await db.commit()
        return author.id, reviewer.id


async def _attempt(maker, call) -> str:
    async with maker() as db:
        try:
            await call(db)
        except HTTPException as error:
            await db.rollback()
            detail = error.detail if isinstance(error.detail, dict) else {}
            codes = sorted({item["code"] for item in detail.get("errors") or []})
            return str(detail.get("reason") or ",".join(codes) or error.status_code)
        await db.commit()
        return "ok"


async def _run(calls, *, concurrent: bool) -> list[str]:
    if concurrent:
        return list(await asyncio.gather(*calls))
    return [await call for call in calls]


async def _concurrency(url: str, *, concurrent: bool) -> None:
    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        author_id, reviewer_id = await _users(maker)

        async def user(db, user_id):
            return await db.get(User, user_id)

        key = unique_key("s4-probe-confirm")
        async with maker() as db:
            created = await create(db, await user(db, author_id), key, probe_fragment())
            await db.commit()
        fragment_flow_id, v1_id, v1_pin = created["id"], created["versions"][0]["id"], checksum(probe_fragment())

        # 1. Two admins' publishes of one fragment version at the same time: exactly one publishes it.
        async def publish_v1(db):
            await publish(db, v1_id, await user(db, reviewer_id))

        outcomes = await _run([_attempt(maker, publish_v1), _attempt(maker, publish_v1)], concurrent=concurrent)
        assert sorted(outcomes) == ["flow_version_already_published", "ok"], outcomes

        # 2. Two composite publishes pinned to v1 while v2 of the fragment is published: both compile v1.
        drafts = []
        async with maker() as db:
            for _ in range(2):
                composite = await create(db, await user(db, author_id), unique_key("s4-probe"),
                                         probe_composite(key, v1_id, v1_pin))
                drafts.append((composite["versions"][0]["id"], digest(composite["versions"][0]["definition"])))
            saved = await save_flow_draft(db, flow_id=fragment_flow_id, current_user=await user(db, author_id),
                                          payload={"expected_latest_version_id": v1_id, "name": key,
                                                   "definition": probe_fragment(label="v2")})
            v2_id = max(saved["versions"], key=lambda item: item["version"])["id"]
            await db.commit()

        def publish_version(version_id, user_id):
            async def call(db):
                await publish(db, version_id, await user(db, user_id))
            return call

        # D2b2: the composites are published by the second admin too (four-eyes for every phased version).
        outcomes = await _run([_attempt(maker, publish_version(drafts[0][0], reviewer_id)),
                               _attempt(maker, publish_version(v2_id, reviewer_id)),
                               _attempt(maker, publish_version(drafts[1][0], reviewer_id))], concurrent=concurrent)
        assert outcomes == ["ok", "ok", "ok"], outcomes
        async with maker() as db:
            for version_id, compiled in drafts:
                row = await db.get(FlowDefinitionVersion, version_id)
                assert row.status == "published" and digest(row.definition_json) == compiled
                assert row.runtime_settings["composition"]["fragments"][0]["version_id"] == v1_id

        # 3. A composite publish racing the unpublish of its pinned fragment: one consistent order, never a 500.
        async with maker() as db:
            composite = await create(db, await user(db, author_id), unique_key("s4-probe"),
                                     probe_composite(key, v1_id, v1_pin))
            await db.commit()

        async def unpublish_v1(db):
            await unpublish_flow_definition_version(db, version_id=v1_id, current_user=await user(db, reviewer_id))

        outcomes = await _run([_attempt(maker, publish_version(composite["versions"][0]["id"], reviewer_id)),
                               _attempt(maker, unpublish_v1)], concurrent=concurrent)
        assert outcomes in (["ok", "ok"], ["fragment_not_published", "ok"]), outcomes
        async with maker() as db:
            row = await db.get(FlowDefinitionVersion, composite["versions"][0]["id"])
            assert row.status == ("published" if outcomes[0] == "ok" else "draft")
            assert (await db.get(FlowDefinitionVersion, v1_id)).status == "archived"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("dialect", DIALECTS)
def test_pins_and_publishes_are_safe_under_concurrent_publishes(dialect, tmp_path: Path):
    with migrated_database(dialect, tmp_path) as database:
        asyncio.run(_concurrency(database.url, concurrent=dialect == "postgresql"))
