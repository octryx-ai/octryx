"""Word template resolution for the deterministic document composer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import ToolContext


class DocumentTemplateError(RuntimeError):
    pass


@dataclass
class DocumentTemplateChoice:
    path: Path | None
    resolution: dict[str, Any]
    catalog: list[dict[str, Any]]
    needs_selection: bool


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _matches(entry: dict[str, Any], selector: str) -> bool:
    selector = _normalize(selector)
    if not selector:
        return False
    return selector in {
        _normalize(entry.get("template_id")),
        _normalize(entry.get("display_name")),
        _normalize(entry.get("source_file_name")),
        _normalize(Path(str(entry.get("source_file_name") or "")).stem),
    }


def _catalog_view(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "template_id": str(entry.get("template_id") or ""),
            "display_name": str(entry.get("display_name") or ""),
            "description": str(entry.get("description") or ""),
            "source_file_name": str(entry.get("source_file_name") or ""),
        }
        for entry in templates
    ]


async def resolve_document_template(
    context: ToolContext,
    *,
    profile_id: str = "",
    template_path: str = "",
    template: str = "",
) -> DocumentTemplateChoice:
    if template_path.strip():
        explicit = Path(template_path.strip()).expanduser()
        if not explicit.is_file():
            raise DocumentTemplateError(f"template_path '{template_path}' is not a file")
        return DocumentTemplateChoice(
            path=explicit,
            resolution={"source": "explicit_template_path", "path": str(explicit)},
            catalog=[],
            needs_selection=False,
        )

    if context.db is None:
        raise DocumentTemplateError(
            "No database session available to resolve a corporate identity profile; "
            "pass template_path explicitly."
        )

    from ...services.corp_identity_service import (
        get_corp_identity_profile_detail,
        get_default_corp_identity_profile,
    )

    normalized_profile_id = profile_id.strip()
    if normalized_profile_id:
        profile = await get_corp_identity_profile_detail(context.db, normalized_profile_id)
    else:
        profile = await get_default_corp_identity_profile(context.db)
    if not isinstance(profile, dict) or not profile:
        raise DocumentTemplateError(
            "No corporate identity profile is available. Upload a Word template as a "
            "corporate identity profile, or pass template_path explicitly."
        )

    templates = [
        entry
        for entry in ((profile.get("templates") or {}).get("docx") or [])
        if isinstance(entry, dict) and Path(str(entry.get("source_path") or "")).is_file()
    ]
    if not templates:
        raise DocumentTemplateError(
            f"Corporate identity profile '{profile.get('id') or normalized_profile_id}' has no Word "
            "(.docx/.dotx) template. Upload one, or pass template_path explicitly."
        )

    profile_meta = {
        "profile_id": str(profile.get("id") or normalized_profile_id),
        "profile_name": str(profile.get("name") or ""),
    }
    catalog = _catalog_view(templates)

    selector = template.strip()
    if selector:
        chosen = next((entry for entry in templates if _matches(entry, selector)), None)
        if chosen is None:
            raise DocumentTemplateError(
                f"No Word template named '{template}' in this profile. Available: "
                + ", ".join(entry["display_name"] or entry["source_file_name"] for entry in catalog)
            )
        return DocumentTemplateChoice(
            path=Path(str(chosen.get("source_path"))),
            resolution={**profile_meta, "source": "corp_identity_profile", "template_id": chosen.get("template_id"),
                        "template_name": chosen.get("display_name"), "path": str(chosen.get("source_path"))},
            catalog=catalog,
            needs_selection=False,
        )

    if len(templates) == 1:
        only = templates[0]
        return DocumentTemplateChoice(
            path=Path(str(only.get("source_path"))),
            resolution={**profile_meta, "source": "corp_identity_profile", "template_id": only.get("template_id"),
                        "template_name": only.get("display_name"), "path": str(only.get("source_path"))},
            catalog=catalog,
            needs_selection=False,
        )

    # Several templates, none named: hand back the catalog so the caller picks a
    # purpose explicitly rather than the tool guessing one.
    return DocumentTemplateChoice(
        path=None,
        resolution={**profile_meta, "source": "corp_identity_profile"},
        catalog=catalog,
        needs_selection=True,
    )


__all__ = ["resolve_document_template", "DocumentTemplateChoice", "DocumentTemplateError"]
