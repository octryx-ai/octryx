"""Workspace isolation and authorization for the Evidence slice."""

from __future__ import annotations

import pytest

from app.services.knowledge.access.authorization import WorkspaceWriteForbiddenError, authorize_workspace
from app.services.knowledge.ledger.errors import WORKSPACE_NOT_FOUND_DETAIL, WorkspaceNotAccessibleError
from app.services.knowledge.ledger.queries import get_source_detail, list_sources
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
)
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex
from tests.support.knowledge_evidence_isolation_support import _authorized, _ingest


async def test_unknown_foreign_and_malformed_workspaces_are_indistinguishable(db):
    owned = await seed_workspace(db)
    foreign = await seed_workspace(db)
    outsider_id = await seed_outsider(db)
    outsider = await fetch_user(db, outsider_id)
    await seed_member(db, workspace_id=owned, role="admin")

    refusals = []
    for candidate in (new_workspace_id(), foreign, "not-a-uuid", "", None, "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(WorkspaceNotAccessibleError) as caught:
            await authorize_workspace(db, current_user=outsider, workspace_id=candidate)
        refusals.append((type(caught.value), str(caught.value), caught.value.state))
    assert len(set(refusals)) == 1
    assert refusals[0][1] == WORKSPACE_NOT_FOUND_DETAIL


async def test_a_reader_may_read_but_not_author(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    user = await fetch_user(db, user_id)

    readable = await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    assert readable.may_author is False

    # 403 only because the caller can already read the Workspace.
    with pytest.raises(WorkspaceWriteForbiddenError):
        await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)


async def test_a_global_admin_cannot_authorize_a_workspace_that_does_not_exist(db, auth_user):
    with pytest.raises(WorkspaceNotAccessibleError):
        await authorize_workspace(db, current_user=auth_user, workspace_id=new_workspace_id())


async def test_identical_bytes_in_two_workspaces_share_nothing(db):
    first_id = await seed_workspace(db)
    second_id = await seed_workspace(db)
    first = await _authorized(db, first_id)
    second = await _authorized(db, second_id)
    runtime, s3, _ = build_runtime()

    a = await _ingest(db, runtime, first)
    b = await _ingest(db, runtime, second)

    assert a.content_sha256 == b.content_sha256
    assert len(s3.objects) == 2
    keys = [key for _, key in s3.objects]
    assert len(set(keys)) == 2
    assert first.workspace.canonical != second.workspace.canonical
    assert all(first.workspace.value.hex in key for key in keys if second.workspace.value.hex not in key)
    assert a.object_created is True and b.object_created is True


async def test_a_workspace_never_lists_or_reads_another_workspaces_source(db):
    first_id = await seed_workspace(db)
    second_id = await seed_workspace(db)
    first = await _authorized(db, first_id)
    second = await _authorized(db, second_id)
    runtime, _, _ = build_runtime()

    owned = await _ingest(db, runtime, first)

    assert [item.source_id for item in await list_sources(db, first)] == [owned.source_id]
    assert await list_sources(db, second) == ()
    from app.services.knowledge.ledger.errors import EvidenceRecordNotFoundError

    with pytest.raises(EvidenceRecordNotFoundError):
        await get_source_detail(db, second, owned.source_id)


async def test_retrieval_never_returns_another_workspaces_evidence(db):
    first_id = await seed_workspace(db)
    second_id = await seed_workspace(db)
    first = await _authorized(db, first_id)
    second = await _authorized(db, second_id)
    evidence_index = FakeEvidenceIndex()
    runtime, _, evidence_index = build_runtime(index=evidence_index)
    projector = EvidenceProjector(runtime)

    await _ingest(db, runtime, first)
    await _ingest(db, runtime, second, payload=b"Only the second workspace mentions Lugano.\n")
    for _ in range(2):
        await projector.project_once(db, worker_id="worker-a")

    from_first = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=first, query_text="datacenter Lugano"
    )
    from_second = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=second, query_text="datacenter Lugano"
    )

    assert [item.text for item in from_first.evidence] == ["The Zurich datacenter hosts the primary cluster."]
    assert [item.text for item in from_second.evidence] == ["Only the second workspace mentions Lugano."]
    workspaces = {entry[1] for entry in evidence_index.requests}
    assert workspaces == {
        first.workspace.canonical,
        second.workspace.canonical,
    }


async def test_a_projection_row_without_a_ledger_span_is_dropped_not_cited(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, evidence_index = build_runtime()
    database = authorized.workspace.canonical

    await _ingest(db, runtime, authorized)
    await EvidenceProjector(runtime).project_once(db, worker_id="worker-a")

    evidence_index.workspace_records(database)["deadbeef" * 4 + ":9"] = {
        "evidence_key": "deadbeef" * 4 + ":9",
        "body_text": "Injected datacenter row that no span backs.",
        "revision_id": "x",
        "span_ordinal": 9,
        # Marked like any projected span, so only the ledger can reject it.
        "acl_keys": ["public"],
    }

    result = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="datacenter"
    )

    assert result.dropped_unresolved == 1
    assert all("Injected" not in item.text for item in result.evidence)
