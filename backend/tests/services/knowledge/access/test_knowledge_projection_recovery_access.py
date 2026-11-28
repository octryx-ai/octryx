"""Projection recovery is reserved to Workspace authors and refuses everyone else with indistinguishable 404 or reader refusals."""

from __future__ import annotations

import pytest

from app.models.project.knowledge_evidence import OUTBOX_STATE_DEAD_LETTER, OUTBOX_STATE_PENDING
from app.services.knowledge.access.authorization import (
    AUTHOR_PROJECT_ROLES,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from app.services.knowledge.ledger.errors import WORKSPACE_NOT_FOUND_DETAIL
from app.services.knowledge.projection import recovery
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
)
from tests.support.knowledge_projection_recovery_support import (  # noqa: F401
    _audit_records,
    _dead_lettered,
    _entry,
    _recover,
    _release_evidence_runtime,
    _url,
    as_user,
)


def _body_without_request_id(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "request_id"}


# --- authorization matrix ----------------------------------------------------


async def test_the_recovery_routes_require_authentication(client, db):
    workspace_id = await seed_workspace(db)
    revision_id = new_workspace_id()
    for suffix in ("requeue", "retry-now"):
        assert (await client.post(_url(workspace_id, revision_id, suffix))).status_code == 401


async def test_a_foreign_and_an_unknown_workspace_render_identical_404_bodies(client, db, as_user):  # noqa: F811
    foreign_id = await seed_workspace(db)
    unknown_id = new_workspace_id()
    as_user(await fetch_user(db, await seed_outsider(db)))
    revision_id = new_workspace_id()

    foreign = await client.post(_url(foreign_id, revision_id, "requeue"))
    unknown = await client.post(_url(unknown_id, revision_id, "requeue"))
    malformed = await client.post(_url("not-a-uuid", revision_id, "requeue"))

    assert foreign.status_code == unknown.status_code == malformed.status_code == 404
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(unknown.json())
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(malformed.json())
    assert foreign.json()["detail"] == WORKSPACE_NOT_FOUND_DETAIL
    assert foreign_id not in foreign.text


async def test_an_unknown_or_foreign_revision_is_the_same_404_as_an_inaccessible_workspace(
    client, db, as_user  # noqa: F811
):
    workspace_id, owner, _, _, _, ingested = await _dead_lettered(db)
    other_workspace = await seed_workspace(db)
    intruder = await fetch_user(db, await seed_member(db, workspace_id=other_workspace, role="admin"))

    # An author of another Workspace, naming the real revision id of this one.
    as_user(intruder)
    foreign = await client.post(_url(other_workspace, ingested.revision_id, "requeue"))
    missing = await client.post(_url(other_workspace, new_workspace_id(), "requeue"))
    assert foreign.status_code == missing.status_code == 404
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(missing.json())
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER

    as_user(owner)
    assert (await client.post(_url(workspace_id, ingested.revision_id, "requeue"))).status_code == 200


async def test_a_reader_may_not_recover_a_projection(client, db, as_user):  # noqa: F811
    workspace_id, _, _, _, _, ingested = await _dead_lettered(db)
    as_user(await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member")))

    for suffix in ("requeue", "retry-now"):
        assert (await client.post(_url(workspace_id, ingested.revision_id, suffix))).status_code == 403
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER
    assert await _audit_records(db, workspace_id) == []


@pytest.mark.parametrize("role", sorted(AUTHOR_PROJECT_ROLES))
async def test_every_established_author_role_may_requeue(client, db, as_user, role):  # noqa: F811
    workspace_id, author, _, _, _, ingested = await _dead_lettered(db, role=role)
    as_user(author)

    response = await client.post(_url(workspace_id, ingested.revision_id, "requeue"))

    assert response.status_code == 200
    assert response.json()["result"] == recovery.RECOVERY_RESULT_REQUEUED
    assert response.json()["recovered"] is True
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_PENDING


async def test_the_service_refuses_a_reader_even_without_the_transport(db):
    workspace_id, _, _, _, _, ingested = await _dead_lettered(db)
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    readable = await authorize_workspace(db, current_user=reader, workspace_id=workspace_id)

    with pytest.raises(WorkspaceWriteForbiddenError):
        await _recover(db, readable, ingested.revision_id, actor_user_id=reader.id)
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER
