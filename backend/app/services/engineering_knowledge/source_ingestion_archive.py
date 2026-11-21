"""Fetching, archiving and parsing source payloads for Engineering Knowledge packs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..document_ingestion.parse import parse_document_file
from .archive_store import (
    engineering_archive_backend,
    write_engineering_archive_bytes,
    write_engineering_archive_text,
)
from .source_ingestion_specs import EngineeringKnowledgeSourceSpec

_REDACTED_HEADER_NAMES = {"authorization", "proxy-authorization", "set-cookie", "set-cookie2"}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _archive_filesystem_path(archive_base_path: Path, relative_path: str) -> Path:
    return archive_base_path.expanduser().resolve() / Path(str(relative_path).replace("\\", "/").lstrip("/"))


def _write_archive_json(relative_path: str, payload: Any, *, archive_base_path: Path) -> None:
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    if engineering_archive_backend() == "filesystem":
        target = _archive_filesystem_path(archive_base_path, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return
    write_engineering_archive_text(
        relative_path,
        content,
        content_type="application/json",
    )


def _safe_headers(headers: Any) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        normalized = str(key or "").lower().strip()
        if not normalized or normalized in _REDACTED_HEADER_NAMES:
            continue
        safe[normalized] = str(value or "")[:500]
    return safe


def _resolve_local_path(source_uri: str, allowed_roots: list[Path]) -> Path:
    parsed = urlsplit(source_uri)
    raw_path = parsed.path if parsed.scheme == "file" else source_uri
    candidate = Path(raw_path).expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError(raw_path)
    roots = [root.expanduser().resolve() for root in allowed_roots]
    if not roots or not any(root == candidate or root in candidate.parents for root in roots):
        raise ValueError("Local engineering knowledge sources must stay inside an allowed root")
    return candidate


def _source_file_name(spec: EngineeringKnowledgeSourceSpec, media_type: str = "") -> str:
    parsed_name = Path(urlsplit(spec.source_uri).path).name or spec.source_key
    suffix = Path(parsed_name).suffix
    if not suffix and media_type:
        suffix = mimetypes.guess_extension(media_type.split(";", 1)[0].strip()) or ""
    return f"{spec.source_key}{suffix or '.bin'}"


def _source_media_type(spec: EngineeringKnowledgeSourceSpec, response_headers: dict[str, str] | None = None) -> str:
    content_type = str((response_headers or {}).get("content-type") or "").strip()
    if content_type:
        return content_type
    return mimetypes.guess_type(_source_file_name(spec))[0] or "application/octet-stream"


async def _fetch_url(
    spec: EngineeringKnowledgeSourceSpec,
    *,
    max_download_bytes: int,
) -> tuple[bytes, str, dict[str, str]]:
    parsed = urlsplit(spec.source_uri)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported source URI scheme: {parsed.scheme or '(none)'}")
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(spec.source_uri, headers={"User-Agent": "Octryx/1.0"})
        response.raise_for_status()
    payload = response.content
    if len(payload) > max_download_bytes:
        raise ValueError(f"Engineering knowledge source exceeds max_download_bytes={max_download_bytes}")
    return payload, str(response.url), _safe_headers(response.headers)



async def _archive_and_parse_payload(
    payload: bytes,
    *,
    archive_base_path: Path,
    raw_relative_path: str,
    parsed_relative_dir: str,
    media_type: str,
) -> tuple[str, str | None, bool]:
    if engineering_archive_backend() == "filesystem":
        raw_file = _archive_filesystem_path(archive_base_path, raw_relative_path)
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
        parsed_dir = _archive_filesystem_path(archive_base_path, parsed_relative_dir)
        parsed_dir.mkdir(parents=True, exist_ok=True)
        parsed = await asyncio.to_thread(parse_document_file, raw_file, parsed_dir=parsed_dir, media_type=media_type)
        parsed_path = str(Path(parsed_relative_dir) / parsed.parsed_path.name) if parsed.parsed_path.exists() else None
        return raw_relative_path, parsed_path, parsed.success

    with tempfile.TemporaryDirectory(prefix="octryx-engineering-archive-") as temp_dir:
        temp_root = Path(temp_dir).resolve()
        raw_file = temp_root / raw_relative_path
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
        parsed_dir = temp_root / parsed_relative_dir
        parsed_dir.mkdir(parents=True, exist_ok=True)
        parsed = await asyncio.to_thread(parse_document_file, raw_file, parsed_dir=parsed_dir, media_type=media_type)
        write_engineering_archive_bytes(
            raw_relative_path,
            payload,
            content_type=media_type or "application/octet-stream",
        )
        parsed_path = None
        if parsed.parsed_path.exists():
            parsed_path = str(parsed.parsed_path.relative_to(temp_root))
            write_engineering_archive_bytes(
                parsed_path,
                parsed.parsed_path.read_bytes(),
                content_type="text/plain",
            )
        return raw_relative_path, parsed_path, parsed.success
