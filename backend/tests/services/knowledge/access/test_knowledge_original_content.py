"""Opening the original of a Workspace Knowledge revision."""

from __future__ import annotations

import pytest

from app.main import app
from app.services.auth import get_current_user
from app.services.knowledge.access.source_acl import restrict_source
from app.services.knowledge.ledger.original import safe_filename
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import (
    fetch_user,
    new_workspace_id,
    seed_member,
    seed_outsider,
    seed_workspace,
)
from tests.knowledge_runtime_support import set_evidence_runtime
from tests.support.knowledge_evidence_s3_support import BUCKET
from tests.support.multipart_admission_support import OVERRIDDEN_USER_CREDENTIAL

BASE = "/api/v1/workspaces"
TEXT = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, s3, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user(db):
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


def _without_request_id(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "request_id"}


async def _upload(client, workspace_id: str, *, source_key: str = "runbook", payload: bytes = TEXT) -> dict:
    response = await client.post(
        f"{BASE}/{workspace_id}/knowledge/sources",
        files={"file": ("ignored.txt", payload, "text/plain")},
        headers=OVERRIDDEN_USER_CREDENTIAL,
        data={"source_key": source_key, "display_title": "Zurich runbook / v2"},
    )
    assert response.status_code == 201
    return response.json()


def _original(workspace_id: str, source_id: str, revision_id: str) -> str:
    return f"{BASE}/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/original"


async def test_a_reader_gets_the_digest_verified_original_with_safe_headers(client, db, as_user, evidence_runtime):
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    as_user(owner)
    created = await _upload(client, workspace_id)

    as_user(reader)
    response = await client.get(_original(workspace_id, created["source_id"], created["revision_id"]))

    assert response.status_code == 200
    assert response.content == TEXT
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-sha256"] == created["content_sha256"]
    assert response.headers["content-disposition"] == 'attachment; filename="Zurich-runbook-v2-r1.txt"'
    for forbidden in (BUCKET, "octryx/test", "sha256/", "ignored.txt"):
        assert forbidden not in str(dict(response.headers))


async def test_a_corrupted_object_is_never_served(client, db, as_user, evidence_runtime):
    _, s3, _ = evidence_runtime
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(owner)
    created = await _upload(client, workspace_id)
    for location in list(s3.objects):
        s3.objects[location] = b"tampered bytes"

    response = await client.get(_original(workspace_id, created["source_id"], created["revision_id"]))

    assert response.status_code == 502
    assert "tampered" not in response.text


async def test_foreign_unknown_mismatched_and_tombstoned_revisions_are_the_same_404(
    client, db, as_user, evidence_runtime
):
    workspace_id = await seed_workspace(db)
    other_workspace = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    intruder = await fetch_user(db, await seed_member(db, workspace_id=other_workspace, role="admin"))
    outsider = await fetch_user(db, await seed_outsider(db))
    as_user(owner)
    first = await _upload(client, workspace_id)
    second = await _upload(client, workspace_id, source_key="other", payload=b"Another runbook.\n")

    unknown = await client.get(_original(workspace_id, first["source_id"], new_workspace_id()))
    mismatched = await client.get(_original(workspace_id, second["source_id"], first["revision_id"]))
    as_user(intruder)
    foreign = await client.get(_original(other_workspace, first["source_id"], first["revision_id"]))
    as_user(outsider)
    non_member = await client.get(_original(workspace_id, first["source_id"], first["revision_id"]))
    as_user(owner)
    assert (await client.delete(f"{BASE}/{workspace_id}/knowledge/sources/{first['source_id']}")).status_code == 200
    tombstoned = await client.get(_original(workspace_id, first["source_id"], first["revision_id"]))

    responses = (unknown, mismatched, foreign, non_member, tombstoned)
    assert {response.status_code for response in responses} == {404}
    record_bodies = {
        str(_without_request_id(response.json())) for response in (unknown, mismatched, foreign, tombstoned)
    }
    assert len(record_bodies) == 1
    assert unknown.json()["detail"]["code"] == "revision_not_found"
    assert non_member.json()["detail"]["code"] == "workspace_not_found"


async def test_an_acl_hidden_source_is_a_404_for_a_member_outside_its_acl(client, db, as_user, evidence_runtime):
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    as_user(owner)
    created = await _upload(client, workspace_id)
    await restrict_source(
        db,
        project_id=workspace_id,
        source_key=created["source_key"],
        restriction="restricted",
        member_emails=(owner.email,),
    )
    await db.commit()

    as_user(reader)
    hidden = await client.get(_original(workspace_id, created["source_id"], created["revision_id"]))
    as_user(owner)
    admitted = await client.get(_original(workspace_id, created["source_id"], created["revision_id"]))

    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "revision_not_found"
    assert admitted.status_code == 200
    assert admitted.content == TEXT


def test_the_download_name_is_ascii_and_bounded():
    assert safe_filename('../../etc/passwd"\r\n', 3, "application/pdf") == "etc-passwd-r3.pdf"
    assert safe_filename("Zürich ✓", 1, "application/x-unknown") == "Z-rich-r1.bin"
    assert safe_filename("", 2, "text/csv") == "source-r2.csv"
    assert len(safe_filename("a" * 500, 1, "text/plain")) <= 90


async def test_a_search_hit_addresses_the_original_it_cites(client, db, as_user, evidence_runtime):

    _, _, evidence_index = evidence_runtime
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(owner)
    created = await _upload(client, workspace_id)
    assert (await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")).json()["applied"] is True

    found = await client.post(f"{BASE}/{workspace_id}/knowledge/search", json={"query_text": "datacenter"})
    hit = found.json()["evidence"][0]

    assert (hit["source_id"], hit["revision_id"]) == (created["source_id"], created["revision_id"])
    opened = await client.get(_original(workspace_id, hit["source_id"], hit["revision_id"]))
    assert opened.status_code == 200 and opened.content == TEXT
