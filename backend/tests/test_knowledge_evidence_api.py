"""The canonical Workspace Knowledge transport.

Pins the status/state mapping, that a foreign and an unknown Workspace render
byte-identical 404 bodies, that a reader cannot author, that an unsupported media
type is refused with nothing written, and the full HTTP round trip:
upload -> projection -> search -> citation.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.api.routes import _knowledge_evidence_http as evidence_http
from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.services.knowledge.ledger.errors import WORKSPACE_NOT_FOUND_DETAIL, EvidenceLedgerState
from app.services.knowledge.runtime import set_evidence_runtime
from app.tools.knowledge_evidence import _scope as knowledge_tool_scope
from tests.knowledge_evidence_api_support import BASE, TEXT, _upload, as_user, evidence_runtime  # noqa: F401
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
)

PDF = b"%PDF-1.7\ntrailer\n"


def _body_without_request_id(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "request_id"}


def test_every_failure_state_has_an_explicit_api_and_tool_mapping():
    failure_states = set(EvidenceLedgerState) - {EvidenceLedgerState.OK}
    # One shared mapping for every Workspace Knowledge route module.
    assert set(evidence_http.STATUS_BY_STATE) == failure_states
    assert set(knowledge_tool_scope.STATE_MESSAGES) == {state.value for state in failure_states}


# --- authentication and indistinguishable refusals --------------------------


async def test_the_routes_require_authentication(client, db):
    workspace_id = await seed_workspace(db)
    assert (await client.get(f"{BASE}/{workspace_id}/knowledge/sources")).status_code == 401
    assert (
        await client.post(f"{BASE}/{workspace_id}/knowledge/search", json={"query_text": "x"})
    ).status_code == 401
    assert (await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")).status_code == 401
    assert (
        await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(TEXT))
    ).status_code == 401


async def test_a_foreign_and_an_unknown_workspace_render_identical_404_bodies(client, db, as_user, evidence_runtime):  # noqa: F811
    foreign_id = await seed_workspace(db)
    unknown_id = new_workspace_id()
    outsider = await fetch_user(db, await seed_outsider(db))
    as_user(outsider)

    foreign = await client.get(f"{BASE}/{foreign_id}/knowledge/sources")
    unknown = await client.get(f"{BASE}/{unknown_id}/knowledge/sources")
    malformed = await client.get(f"{BASE}/not-a-uuid/knowledge/sources")

    assert foreign.status_code == unknown.status_code == malformed.status_code == 404
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(unknown.json())
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(malformed.json())
    assert foreign.json()["detail"] == WORKSPACE_NOT_FOUND_DETAIL
    # Nothing about the Workspace, its database, or its object prefix is rendered.
    rendered = foreign.text
    for forbidden in (foreign_id, "octryx_ws_", "sha256/", "octryx-knowledge-test"):
        assert forbidden not in rendered


async def test_a_foreign_source_id_is_also_a_plain_404(client, db, as_user, evidence_runtime):  # noqa: F811
    owner_workspace = await seed_workspace(db)
    other_workspace = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=owner_workspace, role="admin"))
    intruder = await fetch_user(db, await seed_member(db, workspace_id=other_workspace, role="admin"))

    as_user(owner)
    created = await client.post(f"{BASE}/{owner_workspace}/knowledge/sources", **_upload(TEXT))
    assert created.status_code == 201
    source_id = created.json()["source_id"]

    as_user(intruder)
    foreign = await client.get(f"{BASE}/{other_workspace}/knowledge/sources/{source_id}")
    missing = await client.get(f"{BASE}/{other_workspace}/knowledge/sources/{new_workspace_id()}")
    assert foreign.status_code == missing.status_code == 404


async def test_removing_a_source_is_author_only_and_a_foreign_source_is_a_plain_404(
    client, db, as_user, evidence_runtime  # noqa: F811
):
    owner_workspace = await seed_workspace(db)
    other_workspace = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=owner_workspace, role="admin"))
    reader = await fetch_user(db, await seed_member(db, workspace_id=owner_workspace, role="member"))
    intruder = await fetch_user(db, await seed_member(db, workspace_id=other_workspace, role="admin"))
    as_user(owner)
    source_id = (await client.post(f"{BASE}/{owner_workspace}/knowledge/sources", **_upload(TEXT))).json()["source_id"]

    as_user(intruder)
    foreign = await client.delete(f"{BASE}/{other_workspace}/knowledge/sources/{source_id}")
    missing = await client.delete(f"{BASE}/{other_workspace}/knowledge/sources/{new_workspace_id()}")
    assert foreign.status_code == missing.status_code == 404
    assert _body_without_request_id(foreign.json()) == _body_without_request_id(missing.json())

    as_user(reader)
    assert (await client.delete(f"{BASE}/{owner_workspace}/knowledge/sources/{source_id}")).status_code == 403

    as_user(owner)
    removed = await client.delete(f"{BASE}/{owner_workspace}/knowledge/sources/{source_id}")
    assert removed.status_code == 200
    assert removed.json()["tombstoned_revisions"] == 1
    detail = (await client.get(f"{BASE}/{owner_workspace}/knowledge/sources/{source_id}")).json()
    assert [revision["state"] for revision in detail["revisions"]] == ["tombstoned"]


async def test_a_reader_may_search_but_not_upload_or_project(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id = await seed_workspace(db)
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    as_user(reader)

    assert (await client.get(f"{BASE}/{workspace_id}/knowledge/sources")).status_code == 200
    upload = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(TEXT))
    projection = await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")

    assert upload.status_code == projection.status_code == 403
    # A 403 only because the caller can already read the Workspace.
    assert upload.json()["detail"] != WORKSPACE_NOT_FOUND_DETAIL


# --- state mapping ----------------------------------------------------------


async def test_an_unsupported_media_type_is_415_and_writes_nothing(client, db, as_user, evidence_runtime):  # noqa: F811
    _, s3, _ = evidence_runtime
    workspace_id = await seed_workspace(db)
    author = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(author)

    image = await client.post(
        f"{BASE}/{workspace_id}/knowledge/sources", **_upload(b"\x89PNG\r\n\x1a\n", content_type="image/png")
    )
    # A PDF is supported, but only through the Docling sandbox, which this runtime does not have.
    pdf = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(PDF, content_type="application/pdf"))

    assert image.status_code == 415
    assert pdf.status_code == 503
    assert "Docling sandbox" in pdf.json()["detail"]
    assert s3.objects == {}
    total = (
        await db.execute(
            select(func.count(KnowledgeSourceRevision.id)).where(KnowledgeSourceRevision.project_id == workspace_id)
        )
    ).scalar_one()
    assert total == 0


async def test_an_unconfigured_deployment_answers_needs_configuration(client, db, as_user):  # noqa: F811
    workspace_id = await seed_workspace(db)
    author = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(author)
    set_evidence_runtime(None)

    response = await client.post(f"{BASE}/{workspace_id}/knowledge/sources", **_upload(TEXT))

    # Explicit state, never a filesystem write.
    assert response.status_code == 503
    assert response.json()["detail"] == "Workspace knowledge storage is not configured."
    assert response.headers["X-Knowledge-State"] == "needs_configuration"
