"""Adding a template to an existing profile, and re-extracting a profile from its stored source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .extraction import _build_ai_ready_corp_identity_template, _extract_corp_identity_profile
from .parsing import write_json
from .profile_cleanup import _run_corp_identity_cleanup
from .profile_extraction import _extract_office_template, _extraction_fields, _normalization_fields


async def _merge_template_into_profile(
    db: AsyncSession,
    *,
    profile_id: str,
    file_name: str,
    file_bytes: bytes,
    suffix: str,
    doc_type: str,
) -> dict[str, Any]:
    import uuid as uuid_mod

    from .. import corp_identity_service as svc

    registry = await svc._load_registry(db)
    index = next((idx for idx, item in enumerate(registry) if item.get("id") == profile_id), None)
    if index is None:
        raise FileNotFoundError(profile_id)
    current = registry[index]
    profile_root = Path(str(current.get("profile_root") or "")).expanduser()
    profile_name = str(current.get("name") or "Corporate Identity")
    safe_name = svc._safe_upload_name(file_name)
    source_dir = profile_root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / safe_name
    source_path.write_bytes(file_bytes)

    template_id = uuid_mod.uuid4().hex
    new_entry = {
        "template_id": template_id,
        "type": doc_type,
        "source_path": str(source_path.resolve()),
        "display_name": Path(safe_name).stem.replace("-", " ").replace("_", " ").strip(),
        "source_file_name": safe_name,
        "created_at": svc._utc_now_iso(),
    }

    templates: dict[str, list[dict[str, Any]]] = dict(
        current.get("templates")
        or {
            "pptx": [],
            "docx": [],
            "xlsx": [],
        }
    )
    target = {"profile_id": profile_id, "profile_name": profile_name, "profile_root": profile_root}
    if doc_type == "pptx":
        registry[index] = _merged_presentation_record(svc, current, source_path, templates, new_entry, **target)
    else:
        registry[index] = _merged_office_record(
            svc, current, source_path, templates, new_entry, safe_name=safe_name, doc_type=doc_type, **target
        )

    await svc._save_registry(db, registry)
    return await svc.get_corp_identity_profile_detail(db, profile_id)


def _merged_presentation_record(
    svc: Any,
    current: dict[str, Any],
    source_path: Path,
    templates: dict[str, list[dict[str, Any]]],
    new_entry: dict[str, Any],
    *,
    profile_id: str,
    profile_name: str,
    profile_root: Path,
) -> dict[str, Any]:
    # Re-extract PPTX content and regenerate guide
    extraction = _extract_corp_identity_profile(
        source_path,
        profile_root,
        profile_id=profile_id,
        profile_name=profile_name,
    )
    ai_ready = _build_ai_ready_corp_identity_template(source_path, profile_root)
    return {
        **current,
        "source_path": str(source_path.resolve()),
        "updated_at": svc._utc_now_iso(),
        **_extraction_fields(extraction, ai_ready),
        **_normalization_fields(source_path, profile_root),
        "templates": {
            **templates,
            "pptx": [new_entry],
        },
    }


def _merged_office_record(
    svc: Any,
    current: dict[str, Any],
    source_path: Path,
    templates: dict[str, list[dict[str, Any]]],
    new_entry: dict[str, Any],
    *,
    safe_name: str,
    doc_type: str,
    profile_id: str,
    profile_name: str,
    profile_root: Path,
) -> dict[str, Any]:
    # Extract theme from docx/xlsx
    brand, summary, guide = _extract_office_template(
        profile_root=profile_root, source_path=source_path, profile_id=profile_id, profile_name=profile_name,
        safe_name=safe_name, doc_type=doc_type,
    )
    current_summary = dict(current.get("summary") or {})
    # Merge new colors into existing
    existing_colors = list(current_summary.get("colors") or [])
    new_colors = list(summary.get("colors") or [])
    seen_tokens = {c["token"] for c in existing_colors}
    for c in new_colors:
        if c["token"] not in seen_tokens:
            existing_colors.append(c)
    current_summary["colors"] = existing_colors
    if not current_summary.get("font_family") and summary.get("font_family"):
        current_summary["font_family"] = summary["font_family"]

    record = {
        **current,
        "source_path": str(source_path.resolve()),
        "updated_at": svc._utc_now_iso(),
        "summary": current_summary,
    }
    brand_profile_path = profile_root / "brand-profile.json"
    existing_bp = {}
    if brand_profile_path.exists():
        try:
            existing_bp = json.loads(brand_profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    write_json(brand_profile_path, {**existing_bp, "brand": brand})
    (profile_root / "llm-guide.md").write_text(guide, encoding="utf-8")
    record["templates"] = {
        **templates,
        doc_type: [*(templates.get(doc_type) or []), new_entry],
    }
    return record


async def reextract_corp_identity_profile(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    from .. import corp_identity_service as svc

    registry = await svc._load_registry(db)
    index = next((idx for idx, item in enumerate(registry) if item.get("id") == profile_id), None)
    if index is None:
        raise FileNotFoundError(profile_id)
    current = registry[index]
    source_path = Path(str(current.get("source_path") or "")).expanduser()
    profile_root = Path(str(current.get("profile_root") or "")).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))
    extraction = _extract_corp_identity_profile(
        source_path,
        profile_root,
        profile_id=profile_id,
        profile_name=str(current.get("name") or Path(source_path).stem),
    )
    ai_ready = _build_ai_ready_corp_identity_template(source_path, profile_root)
    registry[index] = {
        **current,
        "updated_at": svc._utc_now_iso(),
        **_extraction_fields(extraction, ai_ready),
        **_normalization_fields(source_path, profile_root),
    }
    await svc._save_registry(db, registry)
    detail = await svc.get_corp_identity_profile_detail(db, profile_id)
    await _run_corp_identity_cleanup(
        db,
        active_profile_id=profile_id,
        corp_identity_root=svc.CORP_IDENTITY_ROOT,
    )
    return detail
