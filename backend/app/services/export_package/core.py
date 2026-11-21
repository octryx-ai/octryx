from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException

from ...models import ExportPackage, ImportLog

SUPPORTED_PACKAGE_TYPES = {"agent", "skill", "task"}


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def checksum_for_content(content_json: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content_json).encode("utf-8")).hexdigest()


def serialize_export_package_row(row: ExportPackage) -> dict[str, Any]:
    return {
        "id": row.id,
        "package_type": row.package_type,
        "entity_name": row.entity_name,
        "source_entity_type": row.source_entity_type,
        "source_entity_id": row.source_entity_id,
        "source_project_id": row.source_project_id,
        "content_json": row.content_json or {},
        "checksum": row.checksum,
        "exported_by": row.exported_by,
        "exported_at": row.exported_at.isoformat() if row.exported_at else None,
    }


def serialize_import_log_row(row: ImportLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "package_id": row.package_id,
        "package_type": row.package_type,
        "package_checksum": row.package_checksum,
        "imported_by": row.imported_by,
        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
        "status": row.status,
        "errors": list(row.errors or []),
        "overwrite_existing": bool(row.overwrite_existing),
        "target_project_id": row.target_project_id,
        "imported_entity_type": row.imported_entity_type,
        "imported_entity_id": row.imported_entity_id,
        "imported_entity_name": row.imported_entity_name,
    }


def normalize_import_package_payload(package_json: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    normalized = dict(package_json or {})
    package_type = str(normalized.get("package_type") or normalized.get("type") or "").strip().lower()
    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported package type")
    content_json = normalized.get("content_json")
    if not isinstance(content_json, dict):
        content_json = dict(normalized)
    checksum = str(normalized.get("checksum") or "").strip()
    expected_checksum = checksum_for_content(content_json)
    if checksum and checksum != expected_checksum:
        raise HTTPException(status_code=400, detail="Package checksum mismatch")
    return package_type, content_json, expected_checksum
