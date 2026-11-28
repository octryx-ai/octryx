"""Getting a source into the bundle: a download or a local file archived under the source's folder, and the
title a parsed source is shown under (``service``)."""

from __future__ import annotations

import html
import mimetypes
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.services.document_ingestion.common import (
    MAX_DOWNLOAD_BYTES,
    _infer_url_file_name,
    _safe_file_name,
    _sha256_bytes,
    _sha256_file,
    _source_archive_dirs,
    _source_id,
    _title_from_text,
    resolve_document_path,
)
from app.services.document_ingestion.parse import ParsedDocument
from app.services.error_facts import error_code, error_text

from ..outbound_egress.public_web import public_web_client
from ..outbound_url_policy import OutboundURLPolicyError

_WEAK_SOURCE_TITLE_PATTERNS = (
    re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$", re.IGNORECASE),
    re.compile(r"^published\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}$", re.IGNORECASE),
    re.compile(r"^table of contents:?$", re.IGNORECASE),
    re.compile(r"^\d{3}\s+(bad request|not found|forbidden|unauthorized)\b", re.IGNORECASE),
    re.compile(r"^\[[^\]]+\]\([^)]+\)\s+documentation$", re.IGNORECASE),
    re.compile(r"^\[\]\([^)]+\)\s+\[[^\]]+\]\([^)]+\)$", re.IGNORECASE),
    re.compile(r"^[-|]+\s*[A-Z ]{3,40}$", re.IGNORECASE),
)
_HTML_TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_H1_TAG_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_REDACTED_RESPONSE_HEADER_NAMES = {"set-cookie", "set-cookie2", "authorization", "proxy-authorization"}


def _safe_response_headers(headers: Any) -> dict[str, str]:
    safe_headers: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key or normalized_key in _REDACTED_RESPONSE_HEADER_NAMES:
            continue
        safe_headers[normalized_key] = str(value or "")[:500]
    return safe_headers


@dataclass(slots=True)
class StoredSource:
    local_path: Path
    content_type: str
    final_url: str
    status_code: int
    response_headers: dict[str, str]
    source_id: str
    content_sha256: str
    archive_dirs: dict[str, Path]


async def download_source(source_url: str, *, origin: str, bundle_root: Path) -> StoredSource | dict[str, Any]:
    try:
        async with public_web_client(timeout=60, headers={"User-Agent": "Octryx/1.0"}) as client:
            response = await client.get(source_url)
            response.raise_for_status()
            payload = response.content
            content_type = response.headers.get("content-type", "")
            status_code = int(response.status_code)
            response_headers = _safe_response_headers(response.headers)
    except Exception as exc:
        failure: dict[str, Any] = {"url": source_url, "bundle_id": bundle_root.name}
        if isinstance(exc, OutboundURLPolicyError):
            failure["error"] = f"Download failed: {error_text('source_download_blocked', exc)}"
            failure["policy_reason"] = error_code(exc.reason)
        else:
            failure["error"] = f"Download failed: {error_text('source_download_failed', exc)}"
        if isinstance(exc, httpx.HTTPStatusError):
            failure["http_status"] = int(exc.response.status_code)
        return failure
    if len(payload) > MAX_DOWNLOAD_BYTES:
        return {"error": f"Downloaded source exceeds {MAX_DOWNLOAD_BYTES} bytes", "url": source_url}
    file_name = _infer_url_file_name(str(response.url), content_type)
    content_sha256 = _sha256_bytes(payload)
    source_id = _source_id(origin, content_sha256)
    archive_dirs = _source_archive_dirs(bundle_root, source_id=source_id, file_name=file_name)
    local_path = (archive_dirs["raw_dir"] / file_name).resolve()
    counter = 2
    while local_path.exists() and local_path.read_bytes() != payload:
        local_path = (
            archive_dirs["raw_dir"] / f"{Path(file_name).stem}-{counter}{Path(file_name).suffix}"
        ).resolve()
        counter += 1
    local_path.write_bytes(payload)
    return StoredSource(local_path, content_type, str(response.url), status_code, response_headers, source_id,
                        content_sha256, archive_dirs)


def store_local_source(path: str, *, origin: str, workspace_root: Path, bundle_root: Path) -> StoredSource:
    source_path = resolve_document_path(path, workspace_root=workspace_root)
    file_name = _safe_file_name(source_path.name)
    content_sha256 = _sha256_file(source_path)
    source_id = _source_id(origin, content_sha256)
    archive_dirs = _source_archive_dirs(bundle_root, source_id=source_id, file_name=file_name)
    local_path = (archive_dirs["raw_dir"] / file_name).resolve()
    if source_path.resolve() != local_path:
        counter = 2
        while local_path.exists() and _sha256_file(local_path) != _sha256_file(source_path):
            local_path = (archive_dirs["raw_dir"] / f"{source_path.stem}-{counter}{source_path.suffix}").resolve()
            counter += 1
        if not local_path.exists():
            shutil.copy2(source_path, local_path)
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    return StoredSource(local_path, content_type, "", 0, {}, source_id, content_sha256, archive_dirs)


def _prefer_source_title_hint(parsed_title: str, title_hint: str) -> str:
    normalized_hint = str(title_hint or "").strip()
    normalized_title = str(parsed_title or "").strip()
    if not normalized_hint:
        return normalized_title
    if not normalized_title:
        return normalized_hint
    if any(pattern.search(normalized_title) for pattern in _WEAK_SOURCE_TITLE_PATTERNS):
        return normalized_hint
    if normalized_title.startswith(("[", "-", "|")):
        return normalized_hint
    if len(normalized_title.split()) < 2 or len(normalized_title.split()) > 18:
        return normalized_hint
    return normalized_title


def _html_title_hint_from_source(raw_html: str) -> str:
    html_text = str(raw_html or "")
    for pattern in (_HTML_TITLE_TAG_PATTERN, _HTML_H1_TAG_PATTERN):
        match = pattern.search(html_text)
        if not match:
            continue
        candidate = html.unescape(_HTML_TAG_PATTERN.sub(" ", str(match.group(1) or "")))
        candidate = re.sub(r"\s+", " ", candidate).strip(" -|\t\r\n")
        if 8 <= len(candidate) <= 180:
            return candidate
    return ""


def source_title(parsed: ParsedDocument, local_path: Path, content_type: str, title_hint: str) -> str:
    parsed_title = _title_from_text(parsed.text, Path(local_path).stem.replace("-", " ").replace("_", " "))
    html_title_hint = ""
    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    is_html_source = (
        normalized_content_type in {"text/html", "application/xhtml+xml"}
        or local_path.suffix.lower() in {".html", ".htm"}
    )
    if is_html_source:
        try:
            html_title_hint = _html_title_hint_from_source(local_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            html_title_hint = ""
    if str(title_hint or "").strip():
        return _prefer_source_title_hint(parsed_title, title_hint)
    if html_title_hint:
        return html_title_hint
    return parsed_title
