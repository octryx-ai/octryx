"""Storage contract helpers for uploaded Office templates."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .storage_contract import build_uploaded_office_template_entry
from .template import office_template_doc_type_for_path

OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX = ".upload.json"
DEFAULT_UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class OfficeTemplateUploadTooLargeError(ValueError):
    """Raised when an uploaded Office template exceeds the allowed size."""


def sanitize_uploaded_file_name(name: str, *, default_name: str = "template.bin") -> str:
    cleaned = Path(name or default_name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-.")
    return cleaned or default_name


def _uploaded_template_content_kind(file_name: str) -> str:
    doc_type = office_template_doc_type_for_path(file_name)
    return doc_type or "unknown"


def _build_uploaded_template_content_identity(
    *,
    file_name: str,
    byte_length: int,
    sha256_hexdigest: str,
) -> str:
    return f"sha256:{_uploaded_template_content_kind(file_name)}:{byte_length}:{sha256_hexdigest}"


def _upload_metadata_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.name}{OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX}")


def _load_upload_metadata(metadata_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _entry_path(entry: dict[str, Any], key: str) -> Path | None:
    value = str(entry.get(key) or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _is_valid_uploaded_template_entry(entry: dict[str, Any]) -> bool:
    source_path = _entry_path(entry, "source_path")
    active_path = _entry_path(entry, "path")
    if source_path is None or active_path is None:
        return False
    if not source_path.exists() or not source_path.is_file():
        return False
    if not active_path.exists() or not active_path.is_file():
        return False

    package_manifest_path = _entry_path(entry, "package_manifest_path")
    if package_manifest_path is not None and (
        not package_manifest_path.exists() or not package_manifest_path.is_file()
    ):
        return False

    storage_contract = entry.get("storage_contract")
    if not isinstance(storage_contract, dict):
        return True

    package_root_raw = str(storage_contract.get("package_root") or "").strip()
    if package_root_raw:
        package_root = Path(package_root_raw).expanduser()
        if not package_root.exists() or not package_root.is_dir():
            return False

    ai_template_raw = str(storage_contract.get("ai_template_path") or "").strip()
    if ai_template_raw:
        ai_template_path = Path(ai_template_raw).expanduser()
        if not ai_template_path.exists() or not ai_template_path.is_file():
            return False

    return True


def _find_existing_uploaded_template_entry(
    *,
    upload_dir: Path,
    content_identity: str,
) -> dict[str, Any] | None:
    for metadata_path in sorted(upload_dir.glob(f"*{OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX}")):
        payload = _load_upload_metadata(metadata_path)
        if payload is None:
            continue
        if str(payload.get("source_content_identity") or "").strip() != content_identity:
            continue
        template_entry = payload.get("template_entry")
        if not isinstance(template_entry, dict):
            continue
        if _is_valid_uploaded_template_entry(template_entry):
            return template_entry
    return None


def _write_upload_metadata(
    *,
    source_path: Path,
    content_identity: str,
    template_entry: dict[str, Any],
) -> None:
    metadata_path = _upload_metadata_path(source_path)
    payload = {
        "source_content_identity": content_identity,
        "template_entry": template_entry,
    }
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def persist_uploaded_office_template(
    *,
    file_name: str,
    read_chunk: Callable[[int], Awaitable[bytes]],
    close_file: Callable[[], Awaitable[None]],
    upload_root: str | Path,
    import_root: str | Path,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> dict[str, Any]:
    upload_dir = Path(upload_root).expanduser().resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_uploaded_file_name(file_name)
    target = (upload_dir / f"{uuid.uuid4().hex}-{safe_name}").resolve()
    if upload_dir not in target.parents:
        raise PermissionError("Upload path must stay inside the workspace")
    written = 0
    hasher = hashlib.sha256()
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await read_chunk(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise OfficeTemplateUploadTooLargeError(f"File '{safe_name}' exceeds the 512 MB upload limit")
                hasher.update(chunk)
                handle.write(chunk)
    finally:
        await close_file()
    content_identity = _build_uploaded_template_content_identity(
        file_name=safe_name,
        byte_length=written,
        sha256_hexdigest=hasher.hexdigest(),
    )
    existing_entry = _find_existing_uploaded_template_entry(
        upload_dir=upload_dir,
        content_identity=content_identity,
    )
    if existing_entry is not None:
        target.unlink(missing_ok=True)
        return existing_entry
    try:
        resolved_import_root = Path(import_root).expanduser().resolve()
        resolved_import_root.mkdir(parents=True, exist_ok=True)
        entry = build_uploaded_office_template_entry(
            source_template=target,
            import_root=resolved_import_root,
        )
        _write_upload_metadata(
            source_path=target,
            content_identity=content_identity,
            template_entry=entry,
        )
        return entry
    except Exception:
        target.unlink(missing_ok=True)
        _upload_metadata_path(target).unlink(missing_ok=True)
        raise


__all__ = [
    "DEFAULT_UPLOAD_CHUNK_SIZE",
    "MAX_UPLOAD_BYTES",
    "OFFICE_TEMPLATE_UPLOAD_METADATA_SUFFIX",
    "OfficeTemplateUploadTooLargeError",
    "persist_uploaded_office_template",
    "sanitize_uploaded_file_name",
]
