"""Core runtime and template helpers for Office tools."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.corp_identity_service import (
    resolve_corp_identity_office_template_path,
    resolve_corp_identity_template_path,
)
from ...services.office.documents import (
    TemplatePathNotAllowedError,
    resolve_explicit_template_path,
    resolve_office_template_path,
    resolve_workspace_path,
)


def _workspace_root(context: ToolContext) -> Path:
    return Path(context.workspace_root or Path.cwd()).resolve()


def _resolve_path(context: ToolContext, raw_path: str) -> Path:
    return resolve_workspace_path(_workspace_root(context), raw_path)


def _artifact_for_path(context: ToolContext, resolved: Path) -> dict[str, Any]:
    return {
        "name": resolved.name,
        "path": str(resolved),
        "relative_path": str(resolved.relative_to(_workspace_root(context))),
        "media_type": "application/vnd.openxmlformats-officedocument"
        if resolved.suffix.lower() in {".docx", ".xlsx", ".pptx"}
        else "",
        "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
    }


async def _engine(operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run one Office engine operation (``services/office/engine/api.py``) off the event loop."""
    return await asyncio.to_thread(operation, *args, **kwargs)


def _template_path_refusal(context: ToolContext, template_path: str) -> dict[str, Any] | None:
    """A closed refusal when an explicit ``template_path`` points outside the workspace and the template stores."""
    if not template_path:
        return None
    try:
        resolve_explicit_template_path(_workspace_root(context), template_path)
    except TemplatePathNotAllowedError as exc:
        return {
            "error": f"{exc.code} template_path must be inside the workspace or a template store",
            "error_code": exc.code,
        }
    return None


async def _resolve_template_for_output(
    context: ToolContext,
    *,
    template_key: str,
    template_path: str,
    doc_type: str,
) -> tuple[Path, dict[str, Any] | None]:
    if template_key or template_path:
        return await resolve_office_template_path(
            db=context.db,
            project_config=context.project_config,
            workspace_root=_workspace_root(context),
            template_key=template_key,
            template_path=template_path,
            doc_type=doc_type,
        )
    if context.db is not None:
        try:
            corp_template, corp_profile = await resolve_corp_identity_office_template_path(
                context.db, doc_type=doc_type
            )
            return corp_template, {
                "key": f"corp-identity:{corp_profile.get('id')}",
                "name": corp_profile.get("name") or "Corporate Identity",
                "doc_type": doc_type,
                "path": str(corp_template),
                "description": f"Default corporate identity {doc_type.upper()} template.",
                "source": "corp_identity",
                "profile_id": corp_profile.get("id"),
            }
        except FileNotFoundError:
            pass
    return await resolve_office_template_path(
        db=context.db,
        project_config=context.project_config,
        workspace_root=_workspace_root(context),
        template_key="",
        template_path="",
        doc_type=doc_type,
    )


def _resolve_builtin_generic_presentation_template() -> tuple[Path, dict[str, Any]]:
    """The tracked neutral template; never scan uploads or borrow another profile."""
    from ...services.office.neutral_presentation_template import NEUTRAL_TEMPLATE_PATH

    if not NEUTRAL_TEMPLATE_PATH.is_file():
        raise FileNotFoundError("presentation_template_unconfigured")
    return NEUTRAL_TEMPLATE_PATH, {
        "id": "builtin-neutral-presentation-template",
        "name": "Neutral Presentation Template",
        "source_slide_count": 0,
        "source_path": str(NEUTRAL_TEMPLATE_PATH),
        "fallback_mode": "builtin_neutral",
    }


async def _resolve_presentation_template_with_fallback(db: Any | None) -> tuple[Path, dict[str, Any], str] | None:
    """Indexed-slide scripts require an explicitly configured corporate template.

    The neutral template has no indexed example slides; it serves create_presentation only.
    """
    if db is None:
        return None
    try:
        template_path, detail = await resolve_corp_identity_template_path(db)
    except FileNotFoundError:
        return None
    return template_path, detail, "corp_identity"


__all__ = [
    name
    for name in vars()
    if not name.startswith("_")
    or name
    in {
        "_artifact_for_path",
        "_engine",
        "_template_path_refusal",
        "_resolve_builtin_generic_presentation_template",
        "_resolve_path",
        "_resolve_presentation_template_with_fallback",
        "_resolve_template_for_output",
        "_workspace_root",
    }
]
