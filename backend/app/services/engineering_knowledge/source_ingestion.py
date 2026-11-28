"""Ingest one Engineering Knowledge source into the pack archive and its database row."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import EngineeringKnowledgePackSource, EngineeringKnowledgePackVersion
from ...time_utils import utc_now
from .archive_paths import EngineeringKnowledgeArchivePaths, build_source_archive_paths
from .source_ingestion_archive import (
    _archive_and_parse_payload,
    _fetch_url,
    _resolve_local_path,
    _sha256_bytes,
    _source_file_name,
    _source_media_type,
    _write_archive_json,
)
from .source_ingestion_audit import audit_engineering_knowledge_source, evaluate_source_freshness
from .source_ingestion_specs import EngineeringKnowledgeSourceAudit, EngineeringKnowledgeSourceSpec

__all__ = [
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "ingest_engineering_knowledge_source",
]

DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


@dataclass(slots=True)
class _ArchivedSource:
    source_audit: EngineeringKnowledgeSourceAudit
    checksum: str | None = None
    raw_path: str | None = None
    parsed_path: str | None = None
    fetch_status: str = "metadata_only"


async def ingest_engineering_knowledge_source(
    db: AsyncSession,
    *,
    pack_version: EngineeringKnowledgePackVersion,
    pack_slug: str,
    source_spec: EngineeringKnowledgeSourceSpec | dict[str, Any],
    archive_base_path: Path,
    allowed_roots: list[Path] | None = None,
    allow_network: bool = False,
    freshness_policy: dict[str, Any] | None = None,
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> EngineeringKnowledgePackSource:
    spec = (
        source_spec
        if isinstance(source_spec, EngineeringKnowledgeSourceSpec)
        else EngineeringKnowledgeSourceSpec.from_mapping(source_spec)
    )
    if not spec.source_key or not spec.title or not spec.source_uri:
        raise ValueError("Engineering knowledge source requires source_key, title, and source_uri")
    source_audit = audit_engineering_knowledge_source(
        spec,
        target_versions=pack_version.target_versions or {},
    )
    paths = build_source_archive_paths(
        pack_slug=pack_slug,
        pack_version=pack_version.version,
        source_key=spec.source_key,
    )
    payload, final_uri, response_headers = await _acquire_payload(
        spec,
        allowed_roots=allowed_roots,
        allow_network=allow_network,
        max_download_bytes=max_download_bytes,
    )
    archived = _ArchivedSource(source_audit=source_audit)
    if payload is not None:
        archived = await _archive_payload(
            spec,
            payload,
            pack_version=pack_version,
            paths=paths,
            archive_base_path=archive_base_path,
            response_headers=response_headers,
        )
    fetched_at = utc_now() if payload is not None else None
    freshness_status = evaluate_source_freshness(fetched_at=fetched_at, freshness_policy=freshness_policy)
    evidence = _evidence_record(spec, archived, final_uri, freshness_status, fetched_at, response_headers)
    evidence_path = str(Path(paths.evidence) / "evidence.json")
    _write_archive_json(evidence_path, evidence, archive_base_path=archive_base_path)

    source = await _upsert_source_row(db, pack_version, spec, archived, final_uri, freshness_status, evidence_path)
    _write_archive_json(str(Path(paths.source_root) / "source.json"), evidence, archive_base_path=archive_base_path)
    return source


async def _acquire_payload(
    spec: EngineeringKnowledgeSourceSpec,
    *,
    allowed_roots: list[Path] | None,
    allow_network: bool,
    max_download_bytes: int,
) -> tuple[bytes | None, str, dict[str, str]]:
    parsed_uri = urlsplit(spec.source_uri)
    if parsed_uri.scheme in {"http", "https"}:
        if allow_network:
            return await _fetch_url(spec, max_download_bytes=max_download_bytes)
        return None, spec.source_uri, {}
    if parsed_uri.scheme in {"", "file"}:
        local_path = _resolve_local_path(spec.source_uri, allowed_roots or [])
        if local_path.stat().st_size > max_download_bytes:
            raise ValueError(f"Engineering knowledge source exceeds max_download_bytes={max_download_bytes}")
        return local_path.read_bytes(), str(local_path), {}
    raise ValueError(f"Unsupported source URI scheme: {parsed_uri.scheme}")


async def _archive_payload(
    spec: EngineeringKnowledgeSourceSpec,
    payload: bytes,
    *,
    pack_version: EngineeringKnowledgePackVersion,
    paths: EngineeringKnowledgeArchivePaths,
    archive_base_path: Path,
    response_headers: dict[str, str],
) -> _ArchivedSource:
    content_text = payload.decode("utf-8", errors="ignore")
    # Re-audit with the fetched content so version and coverage checks can see the text.
    source_audit = audit_engineering_knowledge_source(
        spec,
        target_versions=pack_version.target_versions or {},
        content_text=content_text,
    )
    checksum = _sha256_bytes(payload)
    media_type = _source_media_type(spec, response_headers)
    raw_relative_path = str(Path(paths.raw) / _source_file_name(spec, media_type))
    raw_path, parsed_path, parse_success = await _archive_and_parse_payload(
        payload,
        archive_base_path=archive_base_path,
        raw_relative_path=raw_relative_path,
        parsed_relative_dir=paths.parsed,
        media_type=media_type,
    )
    return _ArchivedSource(
        source_audit=source_audit,
        checksum=checksum,
        raw_path=raw_path,
        parsed_path=parsed_path,
        fetch_status="fetched" if parse_success else "parse_failed",
    )


def _evidence_record(
    spec: EngineeringKnowledgeSourceSpec,
    archived: _ArchivedSource,
    final_uri: str,
    freshness_status: str,
    fetched_at: Any,
    response_headers: dict[str, str],
) -> dict[str, Any]:
    return {
        "source_key": spec.source_key,
        "title": spec.title,
        "source_uri": spec.source_uri,
        "final_uri": final_uri,
        "source_type": spec.source_type,
        "trust_tier": spec.trust_tier,
        "version_label": spec.version_label,
        "checksum": archived.checksum,
        "fetch_status": archived.fetch_status,
        "freshness_status": freshness_status,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "response_headers": response_headers,
        "source_audit": archived.source_audit.to_metadata(),
    }


async def _upsert_source_row(
    db: AsyncSession,
    pack_version: EngineeringKnowledgePackVersion,
    spec: EngineeringKnowledgeSourceSpec,
    archived: _ArchivedSource,
    final_uri: str,
    freshness_status: str,
    evidence_path: str,
) -> EngineeringKnowledgePackSource:
    existing = (
        await db.execute(
            select(EngineeringKnowledgePackSource).where(
                EngineeringKnowledgePackSource.pack_version_id == pack_version.id,
                EngineeringKnowledgePackSource.source_key == spec.source_key,
            )
        )
    ).scalar_one_or_none()
    source = existing or EngineeringKnowledgePackSource(id=str(uuid.uuid4()))
    source.pack_version_id = pack_version.id
    source.source_key = spec.source_key
    source.title = spec.title
    source.source_uri = spec.source_uri
    source.source_type = spec.source_type
    source.trust_tier = spec.trust_tier
    source.version_label = spec.version_label or None
    source.checksum = archived.checksum
    source.fetch_status = archived.fetch_status
    source.freshness_status = freshness_status
    source.raw_archive_path = archived.raw_path
    source.parsed_archive_path = archived.parsed_path
    source.evidence_archive_path = evidence_path
    source.source_metadata = {
        **spec.metadata,
        "final_uri": final_uri,
        "target_version": spec.metadata.get("target_version"),
        "source_audit": archived.source_audit.to_metadata(),
    }
    if existing is None:
        db.add(source)
    await db.flush()
    return source
