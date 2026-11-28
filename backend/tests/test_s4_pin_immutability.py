"""S4.2: a published composite never changes when its fragment does (contract §3.6, D-S4-1); the concurrency
cases also run on PostgreSQL with ``OCTRYX_TEST_POSTGRES_URL``."""

from __future__ import annotations

import copy
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.models import FlowDefinitionVersion
from app.services.flow_draft_service import save_flow_draft
from app.services.workflow_runs.records import new_chat_session, start_run
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
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


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










