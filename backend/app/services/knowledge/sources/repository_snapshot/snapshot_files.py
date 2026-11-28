"""The wanted files' bytes of an open snapshot pass, verified and ingested in bounded batches (``upload.py``)."""

from __future__ import annotations

import base64
import binascii
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from .....models import Session
from .....models.project.knowledge_source_sync import ITEM_STATE_INGESTED, KnowledgeSourceConnector
from ...access.authorization import AuthorizedWorkspace, authorize_tool_workspace
from ...code import repository_index
from ...episodes.policy import public_origin
from ...ingestion.code_ingest import ingest_code_source, prepared_code_text
from ...ledger.errors import EvidenceLedgerError
from ...runtime import get_evidence_runtime
from ..sync.cursor import SyncCursor
from ..sync.git_paths import language_of
from ..sync.git_repository import external_id_of
from ..sync.items import ConnectorRef, load_item, new_item, source_key_for
from .binding import LINKS_HOST, SnapshotRefusal, valid_commit
from .classification import content_outcome, max_snapshot_file_bytes
from .labels import file_title, repository_label
from .protocol_types import FileResult, FilesRequest, FilesResponse
from .remote import parse_remote, platform_blob_url
from .snapshot_pass import REASON_NO_OPEN_PASS, REASON_NO_SOURCE, _open_snapshot, _Pass, _store_cursor, _writable_pass

MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 3 * 1024 * 1024
REASON_BATCH_INVALID = "batch_invalid"
REASON_BATCH_TOO_LARGE = "batch_too_large"


def max_batch_bytes() -> int:
    return max(MAX_BATCH_BYTES, max_snapshot_file_bytes())


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


def _source_url(opened: _Pass, workspace_id: str, connector_key: str, path: str, blob: str) -> str | None:
    if opened.binding.get("links") == LINKS_HOST:
        url = parse_remote(opened.binding.get("remote")).blob_url(opened.head_commit, path)
        if url is not None:
            return url
    return platform_blob_url(public_origin(), workspace_id, connector_key, opened.head_commit, path, blob_sha=blob)


async def _ingest_one(
    db: AsyncSession,
    *,
    opened: _Pass,
    authorized: AuthorizedWorkspace,
    ref: ConnectorRef,
    pass_number: int,
    user_id: str,
    path: str,
    blob: str,
    data: bytes,
) -> FileResult:
    # The ledger ingestion commits its own transaction, so a failure leaves the file wanted.
    outcome = content_outcome(data)
    if outcome is not None:
        return {"path": path, "outcome": "skipped", "reason": outcome}
    external_id = external_id_of(path)
    language = language_of(path)
    try:
        ingested = await ingest_code_source(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            source_key=source_key_for(ref, external_id),
            display_title=file_title(repository_label(dict(opened.connector.scope or {})), path),
            data=data,
            created_by=user_id,
            source_url=_source_url(opened, authorized.project_id, ref.connector_key, path, blob),
            language=language,
            path=path,
        )
    except EvidenceLedgerError as error:
        await db.rollback()
        return {"path": path, "outcome": "failed", "reason": error.state.value}
    await _record_file(db, opened, authorized, ref, pass_number, path, blob, data, external_id, language, ingested)
    return {"path": path, "outcome": "ingested", "reason": None}


async def _record_file(
    db: AsyncSession, opened: _Pass, authorized: AuthorizedWorkspace, ref: ConnectorRef, pass_number: int,
    path: str, blob: str, data: bytes, external_id: str, language, ingested,
) -> None:
    item = await load_item(db, ref, external_id)
    if item is None:
        item = new_item(ref, external_id, state=ITEM_STATE_INGESTED, outcome="created")
        db.add(item)
    else:
        item.last_outcome = "updated" if item.source_id is not None else "created"
    item.source_id = ingested.source_id
    item.content_sha256 = hashlib.sha256(data).hexdigest()
    item.version_marker = blob
    item.state = ITEM_STATE_INGESTED
    item.last_seen_pass = pass_number
    await repository_index.upsert_file(
        db,
        project_id=authorized.project_id,
        connector_id=ref.id,
        path=path,
        blob_sha=blob,
        commit_sha=opened.head_commit,
        language=language,
        source_id=ingested.source_id,
        revision_id=ingested.revision_id,
        text=prepared_code_text(data, path),
    )
    await db.flush()


def _batch_entries(files: object) -> list[tuple[str, str, bytes]] | str:
    if not isinstance(files, list) or not files:
        return REASON_BATCH_INVALID
    if len(files) > MAX_BATCH_FILES:
        return REASON_BATCH_TOO_LARGE
    entries: list[tuple[str, str, bytes]] = []
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or type(entry.get("path")) is not str:
            return REASON_BATCH_INVALID
        blob = valid_commit(entry.get("blob_sha"))
        encoded = entry.get("content_base64")
        if blob is None or type(encoded) is not str or len(encoded) > (max_snapshot_file_bytes() * 4) // 3 + 8:
            return REASON_BATCH_INVALID
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return REASON_BATCH_INVALID
        total += len(data)
        if total > max_batch_bytes():
            return REASON_BATCH_TOO_LARGE
        entries.append((entry["path"], blob, data))
    return entries


async def upload_snapshot_files(
    db: AsyncSession, *, session: Session, workspace_id: str, user_id: str, payload: FilesRequest
) -> FilesResponse | SnapshotRefusal:
    opened = await _writable_pass(
        db, session=session, workspace_id=workspace_id, head_commit=payload.get("head_commit")
    )
    if isinstance(opened, SnapshotRefusal):
        return opened
    snapshot = _open_snapshot(opened.connector, opened.head_commit)
    if snapshot is None:
        return SnapshotRefusal("needs_configuration", REASON_NO_OPEN_PASS)
    entries = _batch_entries(payload.get("files"))
    if isinstance(entries, str):
        return SnapshotRefusal("denied", entries)
    cursor = SyncCursor.load(opened.connector.cursor)
    wanted = dict(snapshot.get("wanted") or {})
    ref = ConnectorRef.of(opened.connector)
    authorized = await authorize_tool_workspace(
        db, user_id=user_id, project_id=workspace_id, allowed_project_ids=[workspace_id]
    )
    ingested_count = int(snapshot.get("ingested") or 0)
    results: list[FileResult] = []
    for path, blob, data in entries:
        if wanted.get(path) != blob:
            results.append({"path": path[:200], "outcome": "skipped", "reason": "not_wanted"})
            continue
        if git_blob_sha1(data) != blob:
            results.append({"path": path, "outcome": "skipped", "reason": "blob_sha_mismatch"})
            continue
        result = await _ingest_one(
            db, opened=opened, authorized=authorized, ref=ref, pass_number=cursor.pass_number, user_id=user_id,
            path=path, blob=blob, data=data,
        )
        results.append(result)
        if result["outcome"] != "failed":
            wanted.pop(path, None)
            ingested_count += result["outcome"] == "ingested"
    # The ingestion commits (and a failure rolls back), so the connector row is read again.
    connector = await db.get(KnowledgeSourceConnector, ref.id, populate_existing=True)
    if connector is None:
        return SnapshotRefusal("needs_configuration", REASON_NO_SOURCE)
    _store_cursor(connector, cursor, {**snapshot, "wanted": wanted, "ingested": ingested_count})
    await db.flush()
    return {"state": "ok", "results": results}
