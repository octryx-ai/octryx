from __future__ import annotations

import re
from pathlib import Path

from ...config import get_settings

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_DASH_RUN_RE = re.compile(r"-{2,}")


class EngineeringKnowledgeArchivePaths:
    source_root: str
    raw: str
    parsed: str
    evidence: str

    def __init__(self, source_root: str, raw: str, parsed: str, evidence: str):
        self.source_root = source_root
        self.raw = raw
        self.parsed = parsed
        self.evidence = evidence


def _safe_segment(value: object, *, fallback: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    text = text.split("/")[-1]
    text = _DASH_RUN_RE.sub("-", _SAFE_SEGMENT_RE.sub("-", text)).strip("._-")
    if not text or text in {".", ".."}:
        text = fallback
    return text[:120]


def _assert_contained(path: Path, root: str) -> None:
    parts = path.parts
    if not parts or parts[0] != root or ".." in parts:
        raise ValueError(f"Archive path escapes {root!r}: {path}")


def build_source_archive_paths(
    *,
    pack_slug: str,
    pack_version: int | str,
    source_key: str,
    root: str = "engineering-knowledge",
) -> EngineeringKnowledgeArchivePaths:
    safe_root = _safe_segment(root, fallback="engineering-knowledge")
    safe_pack = _safe_segment(pack_slug, fallback="pack")
    safe_version = _safe_segment(f"v{pack_version}", fallback="v1")
    safe_source = _safe_segment(source_key, fallback="source")
    source_root = Path(safe_root) / safe_pack / safe_version / "sources" / safe_source
    _assert_contained(source_root, safe_root)
    return EngineeringKnowledgeArchivePaths(
        source_root=str(source_root),
        raw=str(source_root / "raw"),
        parsed=str(source_root / "parsed"),
        evidence=str(source_root / "evidence"),
    )


def default_engineering_knowledge_archive_base_path() -> Path:
    """Return the ignored data directory used for default pack archive files."""
    return Path(get_settings().artifact_store_dir).expanduser().resolve().parent
