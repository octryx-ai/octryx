"""Saving an uploaded corporate identity template as a new profile (or merging it into an existing one)."""

from __future__ import annotations

import json
import shutil
import uuid as uuid_mod
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .extraction import _build_ai_ready_corp_identity_template, _extract_corp_identity_profile
from .guide import generate_llm_guide
from .parsing import write_json
from .profile_cleanup import _activate_profile, _prune_unreferenced_corp_identity_roots
from .profile_extraction import _extract_office_template, _extraction_fields, _normalization_fields
from .profile_merge import _merge_template_into_profile
from .registry import (
    build_source_content_identity,
    find_profile_by_source_content_identity,
)
from .templates import CORP_IDENTITY_TEMPLATE_SUFFIXES


async def save_uploaded_corp_identity_profile(
    db: AsyncSession,
    *,
    file_name: str,
    file_bytes: bytes,
    merge_into_profile_id: str | None = None,
) -> dict[str, Any]:
    from .. import corp_identity_service as svc

    suffix, uploaded_doc_type = _upload_suffix(file_name)
    # Merge mode: add this template to an existing profile
    if merge_into_profile_id:
        return await _merge_template_into_profile(
            db, profile_id=merge_into_profile_id, file_name=file_name, file_bytes=file_bytes, suffix=suffix,
            doc_type=uploaded_doc_type,
        )

    source_content_identity = build_source_content_identity(file_name=file_name, file_bytes=file_bytes)
    existing_profile = await find_profile_by_source_content_identity(db, source_content_identity)
    if existing_profile is not None:
        existing_profile_id = str(existing_profile.get("id") or "").strip()
        if existing_profile_id:
            return await _activate_profile(db, svc, existing_profile_id)
    svc.CORP_IDENTITY_ROOT.mkdir(parents=True, exist_ok=True)
    await _prune_unreferenced_corp_identity_roots(db, corp_identity_root=svc.CORP_IDENTITY_ROOT)
    profile_id = uuid_mod.uuid4().hex
    profile_root, source_path, safe_name = _write_upload_source(svc, profile_id, file_name, file_bytes)
    profile_name = Path(safe_name).stem.replace("-", " ").replace("_", " ").strip() or "Corporate Identity"
    if suffix not in {".potx", ".pptx"}:
        return await _save_non_presentation_profile(
            db,
            profile_id=profile_id,
            profile_name=profile_name,
            profile_root=profile_root,
            source_path=source_path,
            source_content_identity=source_content_identity,
            safe_name=safe_name,
            suffix=suffix,
        )
    extraction, ai_ready = _extract_presentation(svc, source_path, profile_root, profile_id, profile_name)
    registry = await svc._load_registry(db)
    created_at = svc._utc_now_iso()
    record = {
        "id": profile_id,
        "name": profile_name,
        "source_path": str(source_path.resolve()),
        "source_content_identity": source_content_identity,
        "profile_root": str(profile_root.resolve()),
        "created_at": created_at,
        "updated_at": created_at,
        **_extraction_fields(extraction, ai_ready),
        **_normalization_fields(source_path, profile_root),
    }
    registry.insert(0, record)
    await svc._save_registry(db, registry)
    return await _activate_profile(db, svc, profile_id)


def _upload_suffix(file_name: str) -> tuple[str, str]:
    suffix = Path(file_name or "template.potx").suffix.lower()
    supported_suffixes = {item for suffixes in CORP_IDENTITY_TEMPLATE_SUFFIXES.values() for item in suffixes}
    if suffix not in supported_suffixes:
        raise ValueError(
            "Only .potx, .pptx, .dotx, .docx, .xltx, or .xlsx files are supported for corporate identity templates"
        )
    # Determine doc type for the uploaded file
    uploaded_doc_type = next(
        (dt for dt, suffixes in CORP_IDENTITY_TEMPLATE_SUFFIXES.items() if suffix in suffixes),
        "pptx",
    )
    return suffix, uploaded_doc_type


def _write_upload_source(svc: Any, profile_id: str, file_name: str, file_bytes: bytes) -> tuple[Path, Path, str]:
    profile_root = svc._profile_root(profile_id)
    source_dir = profile_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    safe_name = svc._safe_upload_name(file_name)
    source_path = source_dir / safe_name
    source_path.write_bytes(file_bytes)
    return profile_root, source_path, safe_name


def _extract_presentation(
    svc: Any, source_path: Path, profile_root: Path, profile_id: str, profile_name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        extraction = _extract_corp_identity_profile(
            source_path,
            profile_root,
            profile_id=profile_id,
            profile_name=profile_name,
        )
        ai_ready = _build_ai_ready_corp_identity_template(source_path, profile_root)
    except Exception:
        if profile_root.exists():
            shutil.rmtree(profile_root, ignore_errors=True)
        raise
    lean_map_path = Path(ai_ready.get("example_slide_map_path") or "")
    lean_slide_map: dict[str, int] = json.loads(lean_map_path.read_text()) if lean_map_path.exists() else {}
    if lean_slide_map:
        layout_catalog = json.loads(Path(extraction["layout_catalog_path"]).read_text(encoding="utf-8"))
        icon_catalog = json.loads(Path(extraction["icon_catalog_path"]).read_text(encoding="utf-8"))
        updated_guide = generate_llm_guide(extraction["summary"], layout_catalog, icon_catalog, lean_slide_map)
        Path(extraction["guide_path"]).write_text(updated_guide, encoding="utf-8")
    return extraction, ai_ready


async def _save_non_presentation_profile(
    db: AsyncSession,
    *,
    profile_id: str,
    profile_name: str,
    profile_root: Path,
    source_path: Path,
    source_content_identity: str,
    safe_name: str,
    suffix: str,
) -> dict[str, Any]:
    from .. import corp_identity_service as svc

    doc_type = "docx" if suffix in CORP_IDENTITY_TEMPLATE_SUFFIXES["docx"] else "xlsx"
    template_key = f"{doc_type}_template_path"

    # Extract theme from docx/xlsx archive
    brand, summary, guide = _extract_office_template(
        profile_root=profile_root, source_path=source_path, profile_id=profile_id, profile_name=profile_name,
        safe_name=safe_name, doc_type=doc_type,
    )
    _write_office_profile_files(svc, profile_root, doc_type=doc_type, guide=guide, brand_profile={
        "profile_id": profile_id,
        "name": profile_name,
        "source_file_name": safe_name,
        "created_at": svc._utc_now_iso(),
        "summary": summary,
        "brand": brand,
        "layout_catalog": {"summary": {}},
        "icon_catalog": {"total_icons": 0, "categories": {}},
    })
    created_at = svc._utc_now_iso()
    record = {
        "id": profile_id,
        "name": profile_name,
        "source_path": str(source_path.resolve()),
        "source_content_identity": source_content_identity,
        "profile_root": str(profile_root.resolve()),
        "created_at": created_at,
        "updated_at": created_at,
        "summary": summary,
        "brand_profile_path": str((profile_root / "brand-profile.json").resolve()),
        "layout_catalog_path": str((profile_root / "layout-catalog.json").resolve()),
        "icon_catalog_path": str((profile_root / "icon-catalog.json").resolve()),
        "guide_path": str((profile_root / "llm-guide.md").resolve()),
        "ai_template_path": "",
        "ai_pptx_path": "",
        "example_slide_map_path": "",
        "ai_slide_count": 0,
        "ai_layout_count": 0,
        "ai_size_mb": 0,
        template_key: str(source_path.resolve()),
    }
    registry = await svc._load_registry(db)
    registry.insert(0, record)
    await svc._save_registry(db, registry)
    return await _activate_profile(db, svc, profile_id)


def _write_office_profile_files(
    svc: Any, profile_root: Path, *, doc_type: str, guide: str, brand_profile: dict[str, Any]
) -> None:
    write_json(profile_root / "brand-profile.json", brand_profile)
    write_json(
        profile_root / "layout-catalog.json",
        {"layouts": [], "summary": {}, "office_template_type": doc_type},
    )
    write_json(profile_root / "icon-catalog.json", {"total_icons": 0, "categories": {}})
    (profile_root / "llm-guide.md").write_text(guide, encoding="utf-8")
