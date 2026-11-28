from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency handling
    yaml = None

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
TRANSFER_DIR = WORKSPACE_ROOT / "data" / "data-transfer"
EXPORT_DIR = TRANSFER_DIR / "exports"


async def _is_admin_user(db: AsyncSession, user: User) -> bool:
    from ..admin.governance.admin_access_service import is_global_admin

    return await is_global_admin(db, user.id)


def _ensure_yaml_available() -> None:
    if yaml is None:
        raise HTTPException(status_code=409, detail="YAML support is not available in this runtime")


def _write_export_file(job_id: str, export_type: str, format_name: str, content: bytes) -> tuple[str, int]:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = EXPORT_DIR / f"{job_id}-{export_type}.{format_name}"
    file_path.write_bytes(content)
    return str(file_path), file_path.stat().st_size


def _dump_structured_content(payload: Any, format_name: str) -> bytes:
    if format_name == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    if format_name == "yaml":
        _ensure_yaml_available()
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).encode("utf-8")
    raise HTTPException(status_code=400, detail=f"Unsupported structured export format: {format_name}")



def _parse_source_payload(source_format: str, payload_json: Any | None, payload_text: str | None) -> Any:
    normalized_format = str(source_format or "").strip().lower()
    if payload_json is not None:
        return payload_json
    text = str(payload_text or "")
    if normalized_format == "json":
        return json.loads(text)
    if normalized_format == "yaml":
        _ensure_yaml_available()
        return yaml.safe_load(text)
    if normalized_format == "csv":
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]
    raise HTTPException(status_code=400, detail="Unsupported source_format")
