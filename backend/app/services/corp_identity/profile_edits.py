"""The corporate identity brief of a profile, and edits to its templates' metadata."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def get_corp_identity_brief(db: AsyncSession, profile_id: str) -> dict[str, Any]:
    """The unified corporate identity built from all of a profile's templates.

    One shared core (typeface, neutral palette, logo, letterhead) across every
    uploaded template, plus a separate accent palette per medium (presentation
    vs document). Brand assets — logos, icons, images — are extracted into the
    profile and catalogued. Read-only: a stored ``ci_overrides`` value is ignored.
    """
    from pathlib import Path

    from .. import corp_identity_service as svc
    from ..office_identity import corporate_identity_from_templates
    from .ci_assets import extract_ci_assets

    profile = await svc.get_corp_identity_profile_detail(db, profile_id)
    templates = profile.get("templates") if isinstance(profile.get("templates"), dict) else {}
    presentation_paths = [
        str(entry.get("source_path"))
        for entry in (templates.get("pptx") or [])
        if isinstance(entry, dict) and entry.get("source_path")
    ]
    document_paths = [
        str(entry.get("source_path"))
        for entry in (templates.get("docx") or [])
        if isinstance(entry, dict) and entry.get("source_path")
    ]
    brief = corporate_identity_from_templates(
        presentation_paths=presentation_paths, document_paths=document_paths
    )
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    if profile_root.is_dir():
        brief["assets"] = extract_ci_assets(
            profile_root,
            presentation_paths=presentation_paths,
            document_paths=document_paths,
            icon_catalog=profile.get("icon_catalog") if isinstance(profile.get("icon_catalog"), dict) else {},
        )
    brief["profile_id"] = str(profile.get("id") or profile_id)
    brief["profile_name"] = str(profile.get("name") or "")
    return brief


async def update_corp_identity_template(
    db: AsyncSession,
    profile_id: str,
    template_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Persist a template's display name / purpose description durably.

    Metadata is stored under ``template_meta`` keyed by the template's file name,
    which is stable across registry rebuilds — writing into the rebuilt
    ``templates`` list would be discarded on the next load.
    """
    from pathlib import Path

    from .. import corp_identity_service as svc
    from .registry import _build_template_map, load_registry, save_registry

    registry = await load_registry(db)
    index = next((idx for idx, item in enumerate(registry) if item.get("id") == profile_id), None)
    if index is None:
        raise FileNotFoundError(f"Profile '{profile_id}' not found")
    profile = registry[index]
    profile_root = Path(str(profile.get("profile_root") or "")).expanduser()
    templates = _build_template_map(profile, profile_root)
    target = next(
        (
            entry
            for entries in templates.values()
            for entry in entries
            if str(entry.get("template_id") or "") == template_id
        ),
        None,
    )
    if target is None:
        raise FileNotFoundError(f"Template '{template_id}' not found in profile '{profile_id}'")

    source_file_name = str(target.get("source_file_name") or "")
    template_meta = dict(profile.get("template_meta") or {})
    current = dict(template_meta.get(source_file_name) or {})
    for key in ("display_name", "description"):
        if key in updates:
            current[key] = str(updates.get(key) or "").strip()
    template_meta[source_file_name] = current
    registry[index] = {**profile, "template_meta": template_meta}
    await save_registry(db, registry)
    return await svc.get_corp_identity_profile_detail(db, profile_id)
