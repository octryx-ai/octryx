"""Contract: repository snapshots into Knowledge, named and citable.

- the snapshot bind takes an optional display ``name`` and ``version`` label (validated, never cleaned
  up), an author may set them later (``PUT .../repositories/{key}/label``), and the source list shows
  ``<name> (<version>, <short commit>)``;
- opening a snapshot pass enables Knowledge for the Workspace (idempotent, audited) before anything is
  projected;
- the per-file bound is ``Settings.knowledge_snapshot_max_file_bytes`` (default 1 MiB, at most 8 MiB),
  and a batch and the request admit one file of that size;
- a repository file is titled ``<repository>:<path>``, and a code citation reads
  ``[<repository>:<path> L<from>-<to>](link)``.
"""

from __future__ import annotations

import base64
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import AuditLog
from app.models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeEvidenceSpan
from app.services.knowledge.projection import workspace_knowledge_state
from app.services.knowledge.projection.workspace_provisioning import AUDIT_ACTION as ENABLE_AUDIT_ACTION
from app.services.knowledge.retrieval.locator import markdown_citation
from app.services.knowledge.runtime import set_evidence_runtime
from app.services.knowledge.sources.repository_snapshot import upload as upload_module
from app.services.knowledge.sources.repository_snapshot.binding import bind_session_repository, repository_connector
from app.services.knowledge.sources.repository_snapshot.classification import manifest_outcome
from app.services.knowledge.sources.repository_snapshot.labels import (
    display_label,
    file_title,
    repository_label,
    validate_labels,
)
from app.services.knowledge.sources.repository_snapshot.policy import set_local_snapshots_allowed
from app.services.knowledge.sources.repository_snapshot.snapshot_complete import complete_snapshot_pass
from app.services.knowledge.sources.repository_snapshot.snapshot_files import (
    git_blob_sha1,
    max_batch_bytes,
    upload_snapshot_files,
)
from app.services.knowledge.sources.repository_snapshot.upload import open_snapshot_pass
from app.services.knowledge.sources.sync.service_describe import describe_connector
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.mcp_claude_code_parity_support import _gateway_session

HEAD = "b26f235250627a235a2974a22f2317dbef27338d"
REMOTE = "https://github.com/example-org/server-config.git"
BIG = ("key = value\n" * 77_000).encode()[:900 * 1024]  # above the old 512 KiB, below 1 MiB
TOO_BIG = 1024 * 1024 + 1


@pytest.fixture
def runtime():
    built, _, evidence_index = build_runtime()
    set_evidence_runtime(built)
    try:
        yield built, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _bound(db, *, payload_extra: dict | None = None):
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    await set_local_snapshots_allowed(db, workspace_id, allowed=True, actor_id=admin_id)
    await db.commit()
    session = await _gateway_session(db, member_id, workspace_id, str(uuid.uuid4()))
    bound = await bind_session_repository(
        db, session=session, user_id=member_id, workspace_id=workspace_id,
        payload={"remote_url": REMOTE, "head_commit": HEAD, "head_dirty": True, "head_pushed": False,
                 "branch": "main", **(payload_extra or {})},
    )
    await db.commit()
    return workspace_id, member_id, admin_id, session, bound


# --- labels, enablement, file bound and rendering through the launcher's flow -----------------------------------


async def test_a_named_snapshot_enables_knowledge_and_titles_its_files_with_the_repository(db, runtime):
    workspace_id, member_id, _admin, session, bound = await _bound(
        db, payload_extra={"name": "server-config", "version": "config"}
    )
    assert bound["state"] == "bound" and bound["binding"]["label"] == "server-config (config)"
    assert (await workspace_knowledge_state.knowledge_state(db, workspace_id))["state"] == "unknown"

    manifest = [
        {"path": "config/app.ini", "blob_sha": git_blob_sha1(BIG), "size": len(BIG)},
        {"path": "dumps/huge.sql", "blob_sha": "e" * 40, "size": TOO_BIG},
    ]
    opened = await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": manifest},
    )
    assert opened["wanted"] == ["config/app.ini"], "RS-3: 900 KiB is admitted"
    assert opened["skipped"] == [{"path": "dumps/huge.sql", "reason": "skipped_too_large"}]
    # The governed enablement ran (audited) before anything was projected; its state is the
    # environment's (this test database has no Knowledge admin access, so it is needs_configuration).
    assert opened["knowledge"]["state"] != "unknown"
    assert (await workspace_knowledge_state.knowledge_state(db, workspace_id))["state"] == opened["knowledge"]["state"]
    enabled = (await db.execute(select(AuditLog).where(
        AuditLog.action == ENABLE_AUDIT_ACTION, AuditLog.resource_id == workspace_id))).scalars().all()
    assert len(enabled) == 1

    uploaded = await upload_snapshot_files(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": [{"path": "config/app.ini", "blob_sha": git_blob_sha1(BIG),
                                                  "content_base64": base64.b64encode(BIG).decode()}]},
    )
    assert [result["outcome"] for result in uploaded["results"]] == ["ingested"]
    completed = await complete_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id, payload={"head_commit": HEAD}
    )
    assert completed["state"] == "indexed"
    await db.commit()

    titles = set((await db.execute(select(KnowledgeEvidenceSource.display_title).where(
        KnowledgeEvidenceSource.project_id == workspace_id))).scalars())
    assert titles == {"server-config:config/app.ini"}, "RS-4"
    citation = (await db.execute(select(KnowledgeEvidenceSpan.citation).where(
        KnowledgeEvidenceSpan.project_id == workspace_id))).scalars().first()
    assert citation.startswith("server-config:config/app.ini (rev 1, lines 1-")
    connector = await repository_connector(db, workspace_id, bound["binding"]["connector_key"])
    described = await describe_connector(db, connector)
    assert described["display_label"] == "server-config (config, b26f235)"
    # A snapshot completes a pass without a sync run; what it serves is still counted.
    assert described["last_run"] is None and described["cursor"]["completed_passes"] == 1
    assert described["served_items"] == 1


async def test_opening_a_pass_asks_for_knowledge_once_per_pass(db, runtime, monkeypatch):
    workspace_id, member_id, _admin, session, _bound_answer = await _bound(db)
    calls: list[tuple[str, str]] = []

    async def ensure(db, *, authorized, actor_id):
        calls.append((authorized.project_id, actor_id))
        return {"state": "ready", "outcome": "created", "checked_at": None}

    monkeypatch.setattr(upload_module, "ensure_knowledge_enabled", ensure)
    opened = await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id, payload={"head_commit": HEAD, "files": []}
    )
    assert calls == [(workspace_id, member_id)] and opened["knowledge"]["state"] == "ready"
    refused = await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": "d" * 40, "files": []},
    )
    assert refused.reason == "head_commit_mismatch" and len(calls) == 1, "a refused pass enables nothing"


async def test_an_unnamed_snapshot_is_titled_with_the_repository_name(db, runtime):
    workspace_id, _member, _admin, _session, bound = await _bound(db)
    assert bound["binding"]["label"] == "server-config"
    connector = await repository_connector(db, workspace_id, bound["binding"]["connector_key"])
    assert repository_label(dict(connector.scope)) == "server-config"


@pytest.mark.parametrize("extra", [
    {"name": "bad:name"}, {"name": "x" * 81}, {"version": "v" * 41}, {"name": "line\nbreak"},
    {"name": "[link](x)"}, {"name": 7}, {"name": "/absolute"},
])
async def test_an_invalid_label_refuses_the_binding(db, extra):
    _workspace, _member, _admin, session, refused = await _bound(db, payload_extra=extra)
    assert (refused.state, refused.reason) == ("denied", "repository_label_invalid")
    assert "repository_binding" not in (session.metadata_ or {})


# --- label configure route ---------------------------------------------------------------------------------------


async def test_an_author_labels_a_repository_source_and_a_reader_cannot(client, db, auth_headers, runtime):
    workspace_id, _member, _admin, _session, bound = await _bound(db)
    key = bound["binding"]["connector_key"]
    route = f"/api/v1/workspaces/{workspace_id}/knowledge/repositories/{key}/label"
    labelled = await client.put(route, headers=auth_headers, json={"name": "core-api", "version": "release-2"})
    assert labelled.status_code == 200, labelled.text
    assert labelled.json()["label"] == "core-api (release-2)" and labelled.json()["name"] == "core-api"
    kept = await client.put(route, headers=auth_headers, json={"version": "release-3"})
    assert kept.json()["label"] == "core-api (release-3)", "a blank name keeps the stored one"
    invalid = await client.put(route, headers=auth_headers, json={"name": "a:b"})
    assert invalid.status_code == 422 and invalid.json()["detail"]["reason"] == "repository_label_invalid"
    missing = await client.put(
        f"/api/v1/workspaces/{workspace_id}/knowledge/repositories/repo-unknown/label", headers=auth_headers,
        json={"name": "x"},
    )
    assert missing.status_code == 404
    audit = (await db.execute(select(AuditLog.details).where(
        AuditLog.action == "knowledge.repository_source.labelled"))).scalars().all()
    assert audit and all("core-api" not in str(details) for details in audit), "field names only"


# --- file bound settings ------------------------------------------------------------------------------------------


def test_the_snapshot_file_bound_defaults_to_one_mib_and_follows_its_setting(monkeypatch):
    assert get_settings().knowledge_snapshot_max_file_bytes == 1024 * 1024
    assert manifest_outcome("a/b.txt", 1024 * 1024) is None
    assert manifest_outcome("a/b.txt", 1024 * 1024 + 1) == "skipped_too_large"
    assert max_batch_bytes() == 3 * 1024 * 1024
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_SNAPSHOT_MAX_FILE_BYTES", str(6 * 1024 * 1024))
    get_settings.cache_clear()
    assert manifest_outcome("a/b.txt", 5 * 1024 * 1024) is None
    assert max_batch_bytes() == 6 * 1024 * 1024, "a batch admits one file of the bound"
    from app.api.routes.agent_gateway_repository import files_body_limit

    assert files_body_limit() >= 6 * 1024 * 1024 * 4 // 3


@pytest.mark.parametrize("value", [8 * 1024 * 1024 + 1, 1024])
def test_the_bound_stays_within_the_ingestion_limit(monkeypatch, value):
    from app.services.knowledge.ingestion.text_ingest import MAX_TEXT_BYTES

    assert MAX_TEXT_BYTES == 8 * 1024 * 1024
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_SNAPSHOT_MAX_FILE_BYTES", str(value))
    with pytest.raises(ValidationError):
        Settings()


async def test_a_file_above_the_bound_is_refused_in_the_batch(db, runtime):
    workspace_id, member_id, _admin, session, _bound_answer = await _bound(db)
    data = b"x\n" * (600 * 1024)
    await open_snapshot_pass(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": [{"path": "big.txt", "blob_sha": git_blob_sha1(data), "size": 10}]},
    )
    get_settings().knowledge_snapshot_max_file_bytes = 512 * 1024
    refused = await upload_snapshot_files(
        db, session=session, workspace_id=workspace_id, user_id=member_id,
        payload={"head_commit": HEAD, "files": [{"path": "big.txt", "blob_sha": git_blob_sha1(data),
                                                  "content_base64": base64.b64encode(data).decode()}]},
    )
    assert (refused.state, refused.reason) == ("denied", "batch_invalid")


# --- rendering and labels -----------------------------------------------------------------------------------------


def test_a_code_citation_names_the_repository_path_and_lines():
    assert markdown_citation("svc:src/a.py", "https://x.test/a", (), (3, 9)) == "[svc:src/a.py L3-9](https://x.test/a)"
    assert markdown_citation("svc:src/a.py", None, (), (4, 4)) == "svc:src/a.py L4 (no link)"
    assert markdown_citation("Guide", "https://x.test/g", ("Intro",)) == "[Guide § Intro](https://x.test/g)"


def test_file_titles_and_display_labels():
    assert file_title("svc", "src/a.py") == "svc:src/a.py"
    long_path = "p/" * 149 + "x.py"
    assert file_title("svc", long_path) == long_path, "a title past the bound falls back to the path"
    scope = {"remote": "https://github.com/o/core-api", "head_commit": HEAD}
    assert display_label(scope) == "core-api (b26f235)"
    assert display_label({**scope, "display_name": "Core", "version_label": "v2"}) == "Core (v2, b26f235)"
    assert display_label({"remote": "https://github.com/o/core-api"}) == "core-api"
    assert validate_labels("  Core API 2.0 ", None) == ("Core API 2.0", None)
    assert validate_labels("", "  ") == (None, None)
