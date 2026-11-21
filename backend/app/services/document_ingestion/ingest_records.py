"""The bundle's records of one ingested source: its source entry, evidence record, manifests and archived
artifacts (``service``)."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.document_ingestion.archive_store import archive_document_ingestion_artifacts
from app.services.document_ingestion.common import (
    _citation_for_source,
    _document_version_key,
    _infer_document_version,
    _infer_source_publisher,
    _infer_source_year,
    _relative_to_workspace,
    _upsert_json_list,
    _write_json,
)
from app.services.document_ingestion.parse import ParsedDocument
from app.services.document_ingestion.source_fetch import StoredSource

from ...time_utils import utc_now


@dataclass(slots=True)
class BundleRecords:
    """What the last write of a source's records left in the bundle."""

    evidence_records: list[Any]
    sources: list[Any]
    citations: list[Any]
    evidence_manifest_path: Path
    evidence_record_path: Path
    artifacts: list[dict[str, Any]]
    archive_artifacts: list[dict[str, Any]]


def _build_evidence_record(
    *,
    source: dict[str, Any],
    origin_kind: str,
    requested_url: str,
    final_url: str,
    status_code: int,
    response_headers: dict[str, str],
    workspace_root: Path,
) -> dict[str, Any]:
    return {
        "id": source["id"],
        "source_id": source["id"],
        "title": source.get("title") or "",
        "origin": source.get("origin") or "",
        "origin_kind": origin_kind,
        "requested_url": requested_url,
        "final_url": final_url,
        "status_code": status_code,
        "response_headers": response_headers,
        "media_type": source.get("media_type") or "",
        "size_bytes": source.get("size_bytes") or 0,
        "content_id": source.get("content_id") or "",
        "content_sha256": source.get("content_sha256") or "",
        "raw_file_path": source.get("local_file_path") or "",
        "raw_relative_path": source.get("local_relative_path") or "",
        "parsed_path": source.get("parsed_path") or "",
        "parsed_relative_path": source.get("parsed_relative_path") or "",
        "parse_success": source.get("parse_success"),
        "parse_error": source.get("parse_error") or "",
        "bundle_id": source.get("bundle_id") or "",
        "downloaded_at": source.get("ingested_at") or "",
        "workspace_root": str(workspace_root),
    }


def build_source(
    stored: StoredSource, parsed: ParsedDocument, *, title: str, origin: str, bundle_root: Path,
    workspace_root: Path, citation_style: str,
) -> dict[str, Any]:
    local_path, final_url, archive_dirs = stored.local_path, stored.final_url, stored.archive_dirs
    source_id, content_sha256, content_type = stored.source_id, stored.content_sha256, stored.content_type
    ingested_at = utc_now().replace(microsecond=0).isoformat()
    source_year = _infer_source_year(parsed.text, fallback=f"{local_path.name} {final_url or origin}")
    source_publisher = _infer_source_publisher(parsed.text, final_url)
    document_version = _infer_document_version(parsed.text, fallback=f"{local_path.name} {title}")
    document_version_key = _document_version_key(source_id, content_sha256, document_version)
    return {
        "id": source_id,
        "title": title,
        "source_type": "web" if final_url else "file",
        "url": final_url,
        "origin": origin,
        "file_name": local_path.name,
        "suffix": local_path.suffix.lower(),
        "media_type": content_type or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream",
        "size_bytes": local_path.stat().st_size,
        "content_id": f"sha256:{content_sha256}",
        "content_sha256": content_sha256,
        "document_version": document_version,
        "document_version_key": document_version_key,
        "source_root_path": str(archive_dirs["source_root"]),
        "source_root_relative_path": _relative_to_workspace(archive_dirs["source_root"], workspace_root),
        "local_file_path": str(local_path),
        "local_relative_path": _relative_to_workspace(local_path, workspace_root),
        "parsed_path": str(parsed.parsed_path) if parsed.parsed_path else "",
        "parsed_relative_path": (
            _relative_to_workspace(parsed.parsed_path, workspace_root) if parsed.parsed_path else ""
        ),
        "parser": parsed.parser,
        "parse_success": parsed.success,
        "parse_error": parsed.error,
        "bundle_id": bundle_root.name,
        "citation_style": citation_style,
        "authors": [],
        "publisher": source_publisher,
        "year": source_year,
        "ingested_at": ingested_at,
    }


def _content_artifacts(local_path: Path, parsed: ParsedDocument, media_type: str) -> list[dict[str, Any]]:
    content_artifacts = [
        {
            "path": str(local_path),
            "name": local_path.name,
            "media_type": media_type,
            "size_bytes": local_path.stat().st_size,
        }
    ]
    if parsed.parsed_path and parsed.parsed_path.exists():
        content_artifacts.append(
            {
                "path": str(parsed.parsed_path),
                "name": parsed.parsed_path.name,
                "media_type": "text/plain",
                "size_bytes": parsed.parsed_path.stat().st_size,
            }
        )
    return content_artifacts


def _write_source_records(
    source: dict[str, Any], evidence_record: dict[str, Any], evidence_record_path: Path, bundle_root: Path
) -> tuple[list[Any], list[Any], list[Any]]:
    _write_json(evidence_record_path, evidence_record)
    evidence_records = _upsert_json_list(bundle_root / "evidence_manifest.json", evidence_record)
    sources = _upsert_json_list(bundle_root / "sources.json", source)
    citations = _upsert_json_list(bundle_root / "citations.json", _citation_for_source(source))
    return evidence_records, sources, citations


def _first_evidence_record(
    source: dict[str, Any], stored: StoredSource, *, source_url: str, bundle_root: Path, workspace_root: Path
) -> tuple[dict[str, Any], Path, Path]:
    """The evidence record and the source entry, written once before anything is archived."""
    evidence_record = _build_evidence_record(
        source=source,
        origin_kind="url" if source_url else "file",
        requested_url=source_url,
        final_url=stored.final_url,
        status_code=stored.status_code,
        response_headers=stored.response_headers,
        workspace_root=workspace_root,
    )
    evidence_record["source_root_path"] = source["source_root_path"]
    evidence_record["source_root_relative_path"] = source["source_root_relative_path"]
    evidence_record_path = (stored.archive_dirs["evidence_dir"] / "record.json").resolve()
    _write_json(evidence_record_path, evidence_record)
    _upsert_json_list(bundle_root / "evidence_manifest.json", evidence_record)
    evidence_manifest_path = bundle_root / "evidence_manifest.json"
    source["evidence_record_path"] = str(evidence_record_path)
    source["evidence_record_relative_path"] = _relative_to_workspace(evidence_record_path, workspace_root)
    source["evidence_manifest_path"] = str(evidence_manifest_path)
    source["evidence_manifest_relative_path"] = _relative_to_workspace(evidence_manifest_path, workspace_root)
    _upsert_json_list(bundle_root / "sources.json", source)
    _upsert_json_list(bundle_root / "citations.json", _citation_for_source(source))
    return evidence_record, evidence_record_path, evidence_manifest_path


def write_bundle_records(
    source: dict[str, Any], stored: StoredSource, parsed: ParsedDocument, *, source_url: str, bundle_root: Path,
    workspace_root: Path,
) -> BundleRecords:
    """Write the records, archive the content, then the metadata, rewriting the records after each archive step."""
    evidence_record, evidence_record_path, evidence_manifest_path = _first_evidence_record(
        source, stored, source_url=source_url, bundle_root=bundle_root, workspace_root=workspace_root
    )
    content_artifacts = _content_artifacts(stored.local_path, parsed, source["media_type"])
    content_archive_artifacts = archive_document_ingestion_artifacts(
        bundle_id=bundle_root.name,
        source_id=stored.source_id,
        artifacts=content_artifacts,
    )
    source["archive_artifacts"] = content_archive_artifacts
    source["archive_storage_backend"] = (
        content_archive_artifacts[0]["storage_backend"] if content_archive_artifacts else ""
    )
    evidence_record["archive_artifacts"] = content_archive_artifacts
    _write_source_records(source, evidence_record, evidence_record_path, bundle_root)
    metadata_artifacts = [
        {"path": str(bundle_root / "sources.json"), "name": "sources.json", "media_type": "application/json"},
        {"path": str(bundle_root / "citations.json"), "name": "citations.json", "media_type": "application/json"},
        {
            "path": str(evidence_manifest_path),
            "name": "evidence_manifest.json",
            "media_type": "application/json",
        },
        {"path": str(evidence_record_path), "name": evidence_record_path.name, "media_type": "application/json"},
    ]
    _archive_metadata(
        source, evidence_record, content_archive_artifacts, metadata_artifacts, stored.source_id, bundle_root
    )
    evidence_records, sources, citations = _write_source_records(
        source, evidence_record, evidence_record_path, bundle_root
    )
    metadata_archive_artifacts = archive_document_ingestion_artifacts(
        bundle_id=bundle_root.name,
        source_id=stored.source_id,
        artifacts=metadata_artifacts,
    )
    archive_artifacts = [*content_archive_artifacts, *metadata_archive_artifacts]
    source["archive_artifacts"] = archive_artifacts
    return BundleRecords(evidence_records, sources, citations, evidence_manifest_path, evidence_record_path,
                         [*content_artifacts, *metadata_artifacts], archive_artifacts)


def _archive_metadata(
    source: dict[str, Any], evidence_record: dict[str, Any], content_archive_artifacts: list[dict[str, Any]],
    metadata_artifacts: list[dict[str, Any]], source_id: str, bundle_root: Path,
) -> None:
    """Archive the metadata files and point the source and its evidence record at every archived artifact."""
    metadata_archive_artifacts = archive_document_ingestion_artifacts(
        bundle_id=bundle_root.name,
        source_id=source_id,
        artifacts=metadata_artifacts,
    )
    archive_artifacts = [*content_archive_artifacts, *metadata_archive_artifacts]
    source["archive_artifacts"] = archive_artifacts
    source["archive_storage_backend"] = archive_artifacts[0]["storage_backend"] if archive_artifacts else ""
    evidence_record["archive_artifacts"] = archive_artifacts
