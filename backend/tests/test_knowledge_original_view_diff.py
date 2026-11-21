"""Source originals: precise refusals, restored rows, sanitized display, and revision diffs.

Pins that ledger rows restored from another deployment (recording that deployment's bucket
name) are served and referenced, the coded refusals per cause, the allowlist HTML view, and
the explicitly bounded revision diff — all with the original route's authorization.
"""

from __future__ import annotations

from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.services.knowledge.access.authorization import parse_workspace_id
from app.services.knowledge.access.source_acl import restrict_source
from app.services.knowledge.display import revision_diff
from app.services.knowledge.display.revision_diff import line_diff
from app.services.knowledge.objects.keys import workspace_object_key
from app.services.knowledge.retention.reconcile import _referenced_keys
from tests.knowledge_evidence_s3_support import PREFIX
from tests.knowledge_evidence_seed_support import fetch_user, new_workspace_id, seed_member, seed_outsider
from tests.knowledge_original_view_diff_support import (  # noqa: F401
    BASE,
    FIRST,
    _code,
    _owner_and_source,
    _path,
    _set_revision,
    _upload,
    as_user,
    evidence_runtime,
)

SECOND = b"# Runbook\n\nThe Zurich datacenter hosts the primary cluster.\nFailover runs from Bern.\nOn call: Ops.\n"


def _diff(workspace_id, source_id, older, newer) -> str:
    return f"{BASE}/{workspace_id}/knowledge/sources/{source_id}/diff?from_revision_id={older}&to_revision_id={newer}"


def _without_request_id(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "request_id"}


# --- root cause: rows restored from another deployment ------------------------------------------


async def test_a_revision_recorded_under_another_bucket_is_served(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    # What a restore from another deployment leaves behind: the local acceptance stack's bucket name on every row.
    await _set_revision(db, created["revision_id"], object_bucket="octryx-knowledge")

    response = await client.get(_path(workspace_id, created["source_id"], created["revision_id"]))

    assert response.status_code == 200
    assert response.content == FIRST


async def test_reconcile_counts_a_restored_row_as_referenced(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    await _set_revision(db, created["revision_id"], object_bucket="octryx-knowledge")

    referenced = await _referenced_keys(db, workspace_id)

    expected = workspace_object_key(PREFIX, parse_workspace_id(workspace_id), created["content_sha256"])
    assert expected in referenced


# --- precise refusals ---------------------------------------------------------------------------


async def test_each_refusal_of_an_original_has_its_own_code(client, db, as_user, evidence_runtime):  # noqa: F811
    _, s3, _ = evidence_runtime
    workspace_id, owner, created = await _owner_and_source(client, db, as_user)
    stored_key = (await db.get(KnowledgeSourceRevision, created["revision_id"])).object_key
    source_id, revision_id = created["source_id"], created["revision_id"]

    as_user(await fetch_user(db, await seed_outsider(db)))
    no_access = await client.get(_path(workspace_id, source_id, revision_id))
    as_user(owner)
    unknown_workspace = await client.get(_path(new_workspace_id(), source_id, revision_id))
    unknown_revision = await client.get(_path(workspace_id, source_id, new_workspace_id()))

    await _set_revision(db, revision_id, object_key="")
    not_stored = await client.get(_path(workspace_id, source_id, revision_id))

    foreign_key = workspace_object_key(PREFIX, parse_workspace_id(new_workspace_id()), created["content_sha256"])
    await _set_revision(db, revision_id, object_key=foreign_key)
    mismatch = await client.get(_path(workspace_id, source_id, revision_id))

    await _set_revision(db, revision_id, object_key=stored_key)
    s3.objects.clear()
    missing = await client.get(_path(workspace_id, source_id, revision_id))

    assert (no_access.status_code, _code(no_access)) == (404, "workspace_not_found")
    assert _without_request_id(no_access.json()) == _without_request_id(unknown_workspace.json())
    assert (unknown_revision.status_code, _code(unknown_revision)) == (404, "revision_not_found")
    assert (not_stored.status_code, _code(not_stored)) == (404, "original_not_stored")
    assert (mismatch.status_code, _code(mismatch)) == (409, "original_location_mismatch")
    assert (missing.status_code, _code(missing)) == (404, "original_object_missing")
    for response in (unknown_revision, not_stored, mismatch, missing):
        assert "Workspace not found" not in response.text
        assert stored_key not in response.text and "octryx/test" not in response.text


# --- revision diff ------------------------------------------------------------------------------


async def test_two_revisions_of_a_source_diff_with_stats(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, first = await _owner_and_source(client, db, as_user)
    second = await _upload(client, workspace_id, payload=SECOND)
    assert second["revision_ordinal"] == 2

    response = await client.get(_diff(workspace_id, first["source_id"], first["revision_id"], second["revision_id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ok" and body["too_large_reason"] is None
    assert body["stats"] == {"added_lines": 2, "removed_lines": 1}
    assert body["diff"].startswith("--- r1\n+++ r2\n@@")
    assert "-Failover runs from Geneva." in body["diff"] and "+Failover runs from Bern." in body["diff"]
    assert (body["from"]["revision_ordinal"], body["to"]["revision_ordinal"]) == (1, 2)


async def test_the_same_revision_is_identical(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, _, created = await _owner_and_source(client, db, as_user)
    revision_id = created["revision_id"]

    body = (await client.get(_diff(workspace_id, created["source_id"], revision_id, revision_id))).json()

    assert (body["state"], body["diff"], body["stats"]) == ("identical", "", {"added_lines": 0, "removed_lines": 0})


async def test_a_diff_over_its_bounds_says_too_large(client, db, as_user, evidence_runtime, monkeypatch):  # noqa: F811
    workspace_id, _, first = await _owner_and_source(client, db, as_user)
    second = await _upload(client, workspace_id, payload=SECOND)
    url = _diff(workspace_id, first["source_id"], first["revision_id"], second["revision_id"])

    monkeypatch.setattr(revision_diff, "MAX_DIFF_INPUT_LINES", 2)
    by_input = (await client.get(url)).json()
    monkeypatch.setattr(revision_diff, "MAX_DIFF_INPUT_LINES", 10_000)
    monkeypatch.setattr(revision_diff, "MAX_DIFF_OUTPUT_CHARS", 10)
    by_output = (await client.get(url)).json()

    assert (by_input["state"], by_input["too_large_reason"], by_input["diff"]) == ("too_large", "input", None)
    assert (by_output["state"], by_output["too_large_reason"], by_output["diff"]) == ("too_large", "output", None)
    assert by_output["stats"] == {"added_lines": 2, "removed_lines": 1}


async def test_a_diff_has_the_original_routes_authorization(client, db, as_user, evidence_runtime):  # noqa: F811
    workspace_id, owner, first = await _owner_and_source(client, db, as_user)
    second = await _upload(client, workspace_id, payload=SECOND)
    other = await _upload(client, workspace_id, payload=b"Another source.\n", source_key="other")
    reader = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    source_id = first["source_id"]

    cross_source = await client.get(_diff(workspace_id, source_id, first["revision_id"], other["revision_id"]))
    as_user(await fetch_user(db, await seed_outsider(db)))
    outsider = await client.get(_diff(workspace_id, source_id, first["revision_id"], second["revision_id"]))
    await restrict_source(
        db, project_id=workspace_id, source_key="runbook", restriction="restricted", member_emails=(owner.email,)
    )
    await db.commit()
    as_user(reader)
    hidden = await client.get(_diff(workspace_id, source_id, first["revision_id"], second["revision_id"]))
    hidden_view = await client.get(_path(workspace_id, source_id, first["revision_id"], "view"))

    assert (cross_source.status_code, _code(cross_source)) == (404, "revision_not_found")
    assert (outsider.status_code, _code(outsider)) == (404, "workspace_not_found")
    assert (hidden.status_code, _code(hidden)) == (404, "revision_not_found")
    assert (hidden_view.status_code, _code(hidden_view)) == (404, "revision_not_found")


def test_line_diff_counts_content_lines_that_look_like_headers():
    diff = line_diff("a\n--b\nc\n", "a\n++b\nc\n", from_label="r1", to_label="r2")

    assert (diff.added_lines, diff.removed_lines) == (1, 1)
    assert "\n---b\n+++b" in diff.unified
