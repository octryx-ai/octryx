"""Office documents in a workspace: path resolution, template library, file actions, preview and inspection."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.office.action_catalog import (
    OFFICE_ACTION_MODES,
    available_office_action_views,
    office_action_entries,
    office_action_text,
)
from app.services.office.engine import api as engine_api
from app.services.office.template import (
    OFFICE_TEMPLATE_BUILTIN_ROOT,
    built_in_office_template_library,
    merge_office_template_libraries,
    office_template_doc_type_for_path,
    resolve_office_template_entry,
)
from app.services.prompt_catalog import bound_prompt_set, prompt_set_scope, resolve_prompt_set
from app.services.system_config import get_agent_runtime_settings

#: OOXML only: legacy binary formats (.doc/.xls/.ppt) are neither read by the engine nor rendered.
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
OFFICE_INSPECT_MODES = {"stats", "text", "issues", "outline", "annotated", "forms"}


def is_office_document(path: str | Path) -> bool:
    return Path(path).suffix.lower() in OFFICE_EXTENSIONS


def resolve_workspace_path(workspace_root: str | Path, requested_path: str) -> Path:
    root = Path(workspace_root).resolve()
    candidate = Path(str(requested_path or "").strip()).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path must stay inside workspace root: {requested_path}")
    return resolved


def office_document_type(path: str | Path) -> str:
    mapped = office_template_doc_type_for_path(path)
    if mapped:
        return mapped
    return "docx"


async def get_office_template_library(
    *,
    db: AsyncSession | None,
    project_config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    runtime_settings = await get_agent_runtime_settings(db) if db is not None else {}
    project_config = project_config or {}
    runtime_library = runtime_settings.get("office_template_library") or []
    project_library = project_config.get("office_template_library") or []
    builtin_library = built_in_office_template_library()
    # Lowest precedence first: code defaults, then DB-backed runtime config, then project overrides.
    return merge_office_template_libraries(builtin_library, runtime_library, project_library)


#: Uploaded Office templates (admin upload, ``web/_helpers/workspace_artifacts``) live under this root.
OFFICE_TEMPLATE_UPLOAD_ROOT = (Path(__file__).resolve().parents[3] / "uploads" / "office-templates").resolve()


class TemplatePathNotAllowedError(PermissionError):
    code = "office_template_path_not_allowed"


def allowed_template_roots(workspace_root: str | Path) -> list[Path]:
    from .. import corp_identity_service

    return [
        Path(workspace_root).resolve(),
        Path(corp_identity_service.CORP_IDENTITY_ROOT).resolve(),
        OFFICE_TEMPLATE_UPLOAD_ROOT,
        OFFICE_TEMPLATE_BUILTIN_ROOT.resolve(),
    ]


def resolve_explicit_template_path(workspace_root: str | Path, template_path: str) -> Path:
    raw = Path(str(template_path or "").strip()).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (Path(workspace_root).resolve() / raw).resolve()
    if not any(resolved == root or root in resolved.parents for root in allowed_template_roots(workspace_root)):
        raise TemplatePathNotAllowedError(TemplatePathNotAllowedError.code)
    return resolved


def _resolve_configured_template_path(workspace_root: str | Path, configured_path: str) -> Path:
    raw = Path(str(configured_path or "").strip()).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return resolve_workspace_path(workspace_root, str(raw))


async def resolve_office_template_path(
    *,
    db: AsyncSession | None,
    project_config: dict[str, Any] | None,
    workspace_root: str | Path,
    template_key: str = "",
    template_path: str = "",
    doc_type: str = "",
) -> tuple[Path, dict[str, Any] | None]:
    if template_path:
        resolved = resolve_explicit_template_path(workspace_root, template_path)
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(str(resolved))
        return resolved, None
    library = await get_office_template_library(db=db, project_config=project_config)
    entry = resolve_office_template_entry(library, template_key=template_key, doc_type=doc_type)
    if entry is None:
        raise FileNotFoundError(f"Office template not found for key={template_key!r} doc_type={doc_type!r}")
    resolved = _resolve_configured_template_path(workspace_root, str(entry.get("path") or ""))
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved, entry


def list_office_actions_for_path(path: str | Path) -> dict[str, Any]:
    file_type = office_document_type(Path(path))
    return {
        "file_type": file_type,
        "allowed_modes": ["prompt", "tool_plan"],
        "available_views": available_office_action_views(file_type),
        "actions": office_action_entries(file_type),
    }


def resolve_office_action_for_path(path: str | Path, action_id: str, mode: str = "tool_plan") -> dict[str, str]:
    resolved = Path(path)
    file_type = office_document_type(resolved)
    normalized_mode = str(mode or "tool_plan").strip().lower()
    if normalized_mode not in OFFICE_ACTION_MODES:
        raise ValueError(f"unsupported office action mode: {mode}")
    selected = next((item for item in office_action_entries(file_type) if item["id"] == action_id), None)
    if selected is None:
        raise ValueError(f"unsupported office action id: {action_id}")
    return {
        "file_type": file_type,
        "action_id": selected["id"],
        "label": selected["label"],
        "description": selected["description"],
        "mode": normalized_mode,
        "text": office_action_text(resolved, selected["id"], normalized_mode),
    }


async def resolve_office_action(
    db: AsyncSession, path: str | Path, *, action_id: str, mode: str = "tool_plan"
) -> dict[str, str]:
    prompt_set = bound_prompt_set() or await resolve_prompt_set(db, workspace_id=None)
    with prompt_set_scope(prompt_set):
        return resolve_office_action_for_path(path, action_id=action_id, mode=mode)


def office_preview_media_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".html", ".htm"}:
        return "text/html"
    guessed = mimetypes.guess_type(str(path))[0]
    return guessed or "application/octet-stream"


def _engine_result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        raise OfficeDocumentError(str(payload.get("error_code") or "office_failed"), str(payload["error"]))
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


class OfficeDocumentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def render_office_preview_html(*, workspace_root: str | Path, path: str) -> str:
    resolved = resolve_workspace_path(workspace_root, path)
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    data = _engine_result(await asyncio.to_thread(engine_api.view, resolved, "html"))
    return str(data.get("html") or "")


async def inspect_office_document(*, workspace_root: str | Path, path: str, mode: str = "stats") -> dict[str, Any]:
    resolved = resolve_workspace_path(workspace_root, path)
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    normalized_mode = str(mode or "stats").strip().lower()
    if normalized_mode not in OFFICE_INSPECT_MODES:
        raise ValueError(f"unsupported office inspect mode: {mode}")
    result = _engine_result(await asyncio.to_thread(engine_api.view, resolved, normalized_mode))
    return {
        "file_name": resolved.name,
        "file_path": str(resolved),
        "file_type": office_document_type(resolved),
        "media_type": office_preview_media_type(resolved),
        "size_bytes": resolved.stat().st_size,
        "mode": normalized_mode,
        "summary": _inspect_summary(normalized_mode, result),
        "content": result,
        "stats": result if normalized_mode == "stats" else None,
    }


def _inspect_summary(mode: str, result: dict[str, Any]) -> dict[str, Any]:
    if mode == "stats":
        return {
            "paragraphs": result.get("paragraphs"),
            "total_characters": result.get("totalCharacters"),
            "style_count": len(result["styleDistribution"]) if isinstance(result.get("styleDistribution"), dict) else None,
            "font_count": len(result["fontUsage"]) if isinstance(result.get("fontUsage"), dict) else None,
        }
    if mode == "text":
        visible = result.get("elements") or result.get("slides") or result.get("sheets") or []
        return {"total_elements": result.get("totalElements", result.get("totalSlides")), "visible_elements": len(visible)}
    if mode == "issues":
        issues = result.get("issues") if isinstance(result.get("issues"), list) else []
        return {"count": result.get("count", len(issues)), "visible_issues": len(issues)}
    if mode == "outline":
        headings = result.get("headings") if isinstance(result.get("headings"), list) else []
        return {"headings": len(headings), "tables": result.get("tables"), "images": result.get("images")}
    if mode == "annotated":
        content = result.get("Content") if isinstance(result.get("Content"), str) else ""
        return {"characters": len(content), "lines": len([line for line in content.splitlines() if line.strip()])}
    fields = result.get("fields") if isinstance(result.get("fields"), list) else []
    return {
        "protection": result.get("protection"),
        "protection_enforced": result.get("protectionEnforced"),
        "field_count": len(fields),
    }
