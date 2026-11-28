"""Text-native media policy: refusal happens before any write."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.media_types import (
    PARSER_NAME,
    PARSER_SANDBOX,
    PARSER_VERSION,
    TEXT_NATIVE_MEDIA_TYPES,
    resolve_text_native_media_type,
)
from app.services.knowledge.ingestion.text_ingest import MAX_UPLOAD_BYTES, ingest_text_source
from app.services.knowledge.ledger.errors import (
    EvidencePayloadTooLargeError,
    InvalidEvidenceRequestError,
    UnsupportedMediaTypeError,
)
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n"
DOCX = b"PK\x03\x04" + b"\x00" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
LEGACY_OLE = b"\xd0\xcf\x11\xe0" + b"\x00" * 32
TEXT = b"A plain paragraph about the Zurich datacenter.\n"


async def _authorized(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    return await authorize_workspace(
        db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id, require_author=True
    )


async def _ingest(db, runtime, authorized, *, data: bytes, media_type):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="doc",
        display_title="Doc",
        declared_media_type=media_type,
        data=data,
        created_by=None,
    )


def test_every_text_native_type_is_accepted():
    for declared in sorted(TEXT_NATIVE_MEDIA_TYPES):
        assert resolve_text_native_media_type(declared, TEXT) in set(TEXT_NATIVE_MEDIA_TYPES.values())
        assert resolve_text_native_media_type(f"{declared}; charset=utf-8", TEXT) == (
            TEXT_NATIVE_MEDIA_TYPES[declared]
        )


def test_types_needing_the_sandboxed_parser_are_refused():
    for declared in (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/msword",
        "image/png",
        "image/jpeg",
        "application/zip",
        "application/octet-stream",
        "text/rtf",
    ):
        with pytest.raises(UnsupportedMediaTypeError):
            resolve_text_native_media_type(declared, TEXT)


def test_a_binary_payload_is_refused_even_when_declared_as_text():
    for payload in (PDF, DOCX, PNG, LEGACY_OLE, b"\x00binary", b"\x1f\x8bgzip"):
        with pytest.raises(UnsupportedMediaTypeError):
            resolve_text_native_media_type("text/plain", payload)


def test_an_absent_or_malformed_declared_type_is_refused():
    with pytest.raises(UnsupportedMediaTypeError):
        resolve_text_native_media_type(None, TEXT)
    for malformed in ("", "text", "text/", "/plain", "text/plain; charset=\x00", "a" * 200):
        with pytest.raises((InvalidEvidenceRequestError, UnsupportedMediaTypeError)):
            resolve_text_native_media_type(malformed, TEXT)


def test_undecodable_bytes_are_not_text_native():
    from app.services.knowledge.ingestion.spans import decode_text

    with pytest.raises(UnsupportedMediaTypeError):
        decode_text(b"valid start \xff\xfe invalid utf-8")


async def test_an_unsupported_upload_writes_no_object_and_no_row(db):
    authorized = await _authorized(db)
    runtime, s3, evidence_index = build_runtime()

    for declared, payload in (
        ("application/pdf", PDF),
        ("text/plain", PDF),
        ("image/png", PNG),
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", DOCX),
    ):
        with pytest.raises(UnsupportedMediaTypeError):
            await _ingest(db, runtime, authorized, data=payload, media_type=declared)

    assert s3.objects == {} and s3.puts == []
    assert evidence_index.requests == []
    total = (
        await db.execute(
            select(func.count(KnowledgeSourceRevision.id)).where(
                KnowledgeSourceRevision.project_id == authorized.project_id
            )
        )
    ).scalar_one()
    assert total == 0


async def test_an_oversized_upload_is_refused_before_any_write(db):
    authorized = await _authorized(db)
    runtime, s3, _ = build_runtime()
    with pytest.raises(EvidencePayloadTooLargeError):
        await _ingest(db, runtime, authorized, data=b"x" * (MAX_UPLOAD_BYTES + 1), media_type="text/plain")
    assert s3.objects == {} and s3.puts == []


async def test_an_accepted_upload_records_its_parser_lineage(db):
    authorized = await _authorized(db)
    runtime, _, _ = build_runtime()
    ingested = await _ingest(db, runtime, authorized, data=TEXT, media_type="text/markdown")

    revision = await db.get(KnowledgeSourceRevision, ingested.revision_id)
    assert revision is not None
    assert revision.media_type == "text/markdown"
    assert (revision.parser_name, revision.parser_version, revision.parser_sandbox) == (
        PARSER_NAME,
        PARSER_VERSION,
        PARSER_SANDBOX,
    )
    assert revision.parser_sandbox == "in_process"


def test_the_legacy_subprocess_parser_is_not_reachable_from_the_new_path():
    import ast
    import inspect
    from pathlib import Path

    from app.services import knowledge as package

    # The whole rebuilt Knowledge module, so the rule cannot be escaped by moving code.
    for path in sorted(Path(inspect.getfile(package)).parent.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not any("document_ingestion" in module for module in imported), path.name
        assert not any("knowledge_chunking" in module for module in imported), path.name
