from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_PREVIEW_CHARS = 6000
DEFAULT_CHUNK_CHARS = 2200
DEFAULT_CHUNK_OVERLAP = 250
RESEARCH_WORKSPACE_DIR = "research"
RESEARCH_SOURCES_DIR = "sources"


def _slugify(value: str, *, fallback: str = "document") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:96] or fallback


def _safe_file_name(name: str, *, fallback: str = "document.bin") -> str:
    cleaned = Path(str(name or fallback)).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-.")
    return cleaned or fallback


def _bundle_id(topic: str, bundle_id: str) -> str:
    explicit = _slugify(bundle_id, fallback="")
    if explicit:
        return explicit
    return _slugify(topic, fallback=f"research-{uuid.uuid4().hex[:8]}")


def _ensure_bundle_root(workspace_root: Path, *, topic: str, bundle_id: str) -> Path:
    root = (workspace_root / RESEARCH_WORKSPACE_DIR / _bundle_id(topic, bundle_id)).resolve()
    if workspace_root.resolve() not in root.parents and root != workspace_root.resolve():
        raise ValueError("Research bundle must stay inside the workspace")
    root.mkdir(parents=True, exist_ok=True)
    (root / RESEARCH_SOURCES_DIR).mkdir(parents=True, exist_ok=True)
    return root


def _source_archive_dirs(bundle_root: Path, *, source_id: str, file_name: str) -> dict[str, Path]:
    readable_name = _safe_file_name(Path(file_name).stem, fallback="source")
    source_folder = _safe_file_name(f"{source_id}-{readable_name}", fallback=source_id)
    source_root = (bundle_root / RESEARCH_SOURCES_DIR / source_folder).resolve()
    if bundle_root.resolve() not in source_root.parents:
        raise ValueError("Research source must stay inside the bundle")
    raw_dir = source_root / "raw"
    parsed_dir = source_root / "parsed"
    evidence_dir = source_root / "evidence"
    for path in (raw_dir, parsed_dir, evidence_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "source_root": source_root,
        "raw_dir": raw_dir,
        "parsed_dir": parsed_dir,
        "evidence_dir": evidence_dir,
    }


def _relative_to_workspace(path: Path, workspace_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _upsert_json_list(path: Path, item: dict[str, Any], *, key: str = "id") -> list[dict[str, Any]]:
    rows = _read_json(path, [])
    if not isinstance(rows, list):
        rows = []
    item_key = str(item.get(key) or "").strip()
    next_rows: list[dict[str, Any]] = []
    replaced = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if item_key and str(row.get(key) or "").strip() == item_key:
            next_rows.append(item)
            replaced = True
        else:
            next_rows.append(row)
    if not replaced:
        next_rows.append(item)
    _write_json(path, next_rows)
    return next_rows


def resolve_document_path(raw_path: str, *, workspace_root: Path) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("path is required")
    candidate = Path(text).expanduser()
    search_candidates = []
    if candidate.is_absolute():
        search_candidates.append(candidate.resolve())
    else:
        search_candidates.extend(
            [
                (workspace_root / candidate).resolve(),
                (REPO_ROOT / candidate).resolve(),
            ]
        )
    for path in search_candidates:
        if not path.exists():
            continue
        allowed_roots = {workspace_root.resolve(), REPO_ROOT.resolve()}
        if any(root == path or root in path.parents for root in allowed_roots):
            return path
    raise FileNotFoundError(text)


def _infer_url_file_name(url: str, content_type: str) -> str:
    parsed = urlsplit(url)
    name = _safe_file_name(Path(parsed.path).name, fallback="")
    if name and "." in name:
        return name
    suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".html"
    return _safe_file_name(f"{parsed.netloc or 'source'}{suffix}")


def _title_from_text(text: str, fallback: str) -> str:
    for line in str(text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" #\t")
        if 8 <= len(cleaned) <= 180:
            return cleaned
    return fallback


def _infer_source_year(text: str, fallback: str = "") -> str:
    candidates = re.findall(r"\b(19\d{2}|20\d{2})\b", f"{text[:5000]} {fallback}")
    return candidates[-1] if candidates else ""


def _infer_document_version(text: str, fallback: str = "") -> str:
    blob = f"{fallback}\n{text[:8000]}"
    for pattern in (
        r"\bv(?:ersion)?\s*([0-9]+(?:\.[0-9]+){1,5})\b",
        r"\b([0-9]+(?:\.[0-9]+){2,5})\b",
    ):
        match = re.search(pattern, blob, re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _infer_source_publisher(text: str, url: str = "") -> str:
    host = urlsplit(url).netloc.lower()
    if host:
        return re.sub(r"^www\.", "", host)
    return ""


def _source_id(origin: str, content_sha256: str) -> str:
    digest = hashlib.sha256(f"{origin}|{content_sha256}".encode()).hexdigest()[:16]
    return f"src-{digest}"


def _document_version_key(source_id: str, content_sha256: str, document_version: str) -> str:
    version_part = _slugify(document_version, fallback="version") if document_version else "version"
    hash_part = str(content_sha256 or "").strip()[:16] or uuid.uuid4().hex[:16]
    return f"{source_id}@{version_part}-{hash_part}"


def _citation_for_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source["id"],
        "title": source.get("title") or source.get("file_name") or source["id"],
        "authors": source.get("authors") or [],
        "publisher": source.get("publisher") or source.get("organization") or "",
        "year": source.get("year") or "",
        "url": source.get("url") or "",
        "local_file_path": source.get("local_file_path") or "",
        "source_type": source.get("source_type") or "document",
        "citation_style": source.get("citation_style") or "",
        "content_id": source.get("content_id") or "",
        "content_sha256": source.get("content_sha256") or "",
        "origin": source.get("origin") or "",
        "ingested_at": source.get("ingested_at") or "",
    }
