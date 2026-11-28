"""Template resolution for the deterministic presentation composer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import ToolContext


class TemplateResolutionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "presentation_template_unconfigured") -> None:
        super().__init__(message)
        self.code = code


async def resolve_composer_template(
    context: ToolContext,
    *,
    profile_id: str = "",
    template_path: str = "",
) -> tuple[Path, dict[str, Any]]:
    if template_path.strip():
        explicit = Path(template_path.strip()).expanduser()
        if not explicit.is_file():
            raise TemplateResolutionError(f"template_path '{template_path}' is not a file")
        return explicit, {"source": "explicit_template_path", "path": str(explicit)}

    from ...services.corp_identity_service import (
        get_corp_identity_profile_detail,
        get_default_corp_identity_profile,
        resolve_corp_identity_composer_template,
    )

    normalized_profile_id = profile_id.strip()
    if normalized_profile_id:
        if context.db is None:
            raise TemplateResolutionError("A database session is required for an explicit profile.")
        try:
            profile = await get_corp_identity_profile_detail(context.db, normalized_profile_id)
        except FileNotFoundError as exc:
            raise TemplateResolutionError("Corporate identity profile not found.") from exc
    else:
        profile = await get_default_corp_identity_profile(context.db) if context.db is not None else None
    if not isinstance(profile, dict) or not profile:
        if normalized_profile_id:
            raise TemplateResolutionError("Corporate identity profile not found.")
        from ...services.office.presentation_fallback import fallback_template_resolution, presentation_fallback

        fallback = await presentation_fallback(context.db)
        if fallback.path is not None:
            return fallback.path, fallback_template_resolution(fallback)
        raise TemplateResolutionError("Configure a corporate identity or enable the neutral presentation template.")

    resolved = resolve_corp_identity_composer_template(profile)
    path = Path(str(getattr(resolved, "path", "") or ""))
    if not path.is_file():
        raise TemplateResolutionError(
            f"Corporate identity profile '{profile.get('id') or normalized_profile_id}' has no usable "
            "PowerPoint template on disk.", code="corp_identity_template_missing"
        )
    meta: dict[str, Any] = {
        "source": "corp_identity_profile",
        "profile_id": str(profile.get("id") or normalized_profile_id),
        "profile_name": str(profile.get("name") or ""),
        "path": str(path),
    }
    for field in ("origin", "status", "customized", "reason"):
        value = getattr(resolved, field, None)
        if value not in (None, ""):
            meta[field] = value
    # Optional second upload: an example deck the profile carries teaches layout
    # usage (dramaturgy) without contributing brand or content. It only reaches
    # the snapshot when it is actually on disk.
    example_deck = str(profile.get("example_deck_path") or "").strip()
    if example_deck and Path(example_deck).expanduser().is_file():
        meta["example_deck_path"] = str(Path(example_deck).expanduser())
    return path, meta
