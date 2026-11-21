"""Template resolution helpers for corporate identity profiles."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

CORP_IDENTITY_TEMPLATE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "pptx": (".potx", ".pptx"),
    "docx": (".dotx", ".docx"),
    "xlsx": (".xltx", ".xlsx"),
}


def candidate_corp_identity_template_roots(detail: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    for key in ("ai_template_path", "source_path"):
        raw_value = str(detail.get(key) or "").strip()
        if not raw_value:
            continue
        roots.append(Path(raw_value).expanduser().parent)
    raw_profile_root = str(detail.get("profile_root") or "").strip()
    if raw_profile_root:
        profile_root = Path(raw_profile_root).expanduser()
        roots.extend([profile_root / "ai", profile_root / "source", profile_root])
    resolved_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(resolved)
        resolved_roots.append(resolved)
    return resolved_roots


def candidate_corp_identity_template_stems(detail: dict[str, Any]) -> list[str]:
    stems: list[str] = []
    for key in ("ai_template_path", "source_path"):
        raw_value = str(detail.get(key) or "").strip()
        if not raw_value:
            continue
        stem = Path(raw_value).stem.strip()
        if not stem:
            continue
        stems.append(stem)
        stems.append(re.sub(r"-ai$", "", stem, flags=re.IGNORECASE))
    deduped: list[str] = []
    seen: set[str] = set()
    for stem in stems:
        normalized = stem.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


async def resolve_corp_identity_office_template_path(
    *,
    doc_type: str,
    profile_id: str,
    get_profile_detail: Callable[[str], Awaitable[dict[str, Any]]],
    get_default_profile: Callable[[], Awaitable[dict[str, Any] | None]],
) -> tuple[Path, dict[str, Any]]:
    detail = await get_profile_detail(profile_id) if str(profile_id or "").strip() else await get_default_profile()
    if detail is None:
        raise FileNotFoundError("No corporate identity profile configured")
    normalized_doc_type = str(doc_type or "pptx").strip().lower() or "pptx"
    suffixes = CORP_IDENTITY_TEMPLATE_SUFFIXES.get(normalized_doc_type)
    if suffixes is None:
        raise ValueError(f"unsupported corporate identity document type: {doc_type}")

    explicit_fields_by_type: dict[str, tuple[str, ...]] = {
        "pptx": ("ai_template_path", "ai_pptx_path", "source_path"),
        "docx": ("ai_docx_template_path", "docx_template_path", "word_template_path"),
        "xlsx": ("ai_xlsx_template_path", "xlsx_template_path", "excel_template_path"),
    }
    for field_name in explicit_fields_by_type.get(normalized_doc_type, ()):
        raw_value = str(detail.get(field_name) or "").strip()
        if not raw_value:
            continue
        candidate = Path(raw_value).expanduser()
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in suffixes:
            return candidate.resolve(), detail

    roots = candidate_corp_identity_template_roots(detail)
    stems = candidate_corp_identity_template_stems(detail)
    for root in roots:
        for stem in stems:
            for suffix in suffixes:
                candidate = (root / f"{stem}{suffix}").resolve()
                if candidate.exists() and candidate.is_file():
                    return candidate, detail
        for suffix in suffixes:
            for candidate in sorted(root.glob(f"*{suffix}")):
                if candidate.is_file():
                    return candidate.resolve(), detail

    raise FileNotFoundError(
        f"No corporate identity {normalized_doc_type.upper()} template configured for profile {detail.get('id')}"
    )
