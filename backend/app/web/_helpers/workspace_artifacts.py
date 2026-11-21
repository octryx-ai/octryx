"""Workspace artifact and upload path helpers."""

from __future__ import annotations

import importlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlencode

from ...models import ToolCall
from .workspace_file_payloads import _build_workspace_file_payload

__all__ = [
    "WORKSPACE_ROOT",
    "_workspace_artifact_url",
    "_path_within_root",
    "_chat_upload_root",
    "_office_template_upload_root",
    "_office_template_import_root",
    "_safe_upload_name",
    "_serialize_tool_artifacts",
    "_serialize_session_workspace_files",
]

# Resolve the workspace root relative to this file's location
# app/web/_helpers/workspace_artifacts.py -> app/web/_helpers -> app/web -> app -> backend -> project root
WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
_ARTIFACT_LINE_PATTERN = re.compile(r"(?i)(?:saved\s+(?:as|to)|written\s+to)\s*:\s*(.+)")


def _workspace_root() -> Path:
    try:
        web_context = importlib.import_module("app.web._context")
        candidate = getattr(web_context, "WORKSPACE_ROOT", None)
        if isinstance(candidate, Path):
            return candidate.resolve()
    except Exception:
        pass
    return WORKSPACE_ROOT.resolve()


def _workspace_artifact_url(path: str) -> str:
    return f"/chat/api/artifact?{urlencode({'path': path})}"


def _artifact_preview_url(path: str) -> str:
    return f"/chat/api/artifact-preview?{urlencode({'path': path})}"


def _path_within_root(path: Path, root: Path) -> bool:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _chat_upload_root() -> Path:
    return (_workspace_root() / "uploads" / "chat").resolve()


def _office_template_upload_root() -> Path:
    return (_workspace_root() / "uploads" / "office-templates").resolve()


def _office_template_import_root() -> Path:
    return (_office_template_upload_root() / "imports").resolve()


def _safe_upload_name(name: str) -> str:
    cleaned = Path(name or "upload.bin").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-.")
    cleaned = re.sub(r"-+\.", ".", cleaned)
    return cleaned or "upload.bin"


def _serialize_tool_artifacts(tool_call: ToolCall, *, workspace_root: Path | None = None) -> list[dict]:
    result = tool_call.result if isinstance(tool_call.result, dict) else {}
    raw_artifacts = list(result.get("artifacts") or [])
    compact_result = {}
    preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
    if isinstance(preview.get("compact_result"), dict):
        compact_result = preview["compact_result"]
    effective_result = compact_result or result
    if str(tool_call.tool_name or "").strip() in {"create_diagram", "edit_diagram", "append_diagram"}:
        diagram_id = str(effective_result.get("diagram_id") or "").strip()
        diagram_xml = str(effective_result.get("diagram_xml") or "").strip()
        if diagram_id and diagram_xml:
            title = str(effective_result.get("title") or "Diagram").strip() or "Diagram"
            size_bytes = result.get("payload_size_bytes") or len(diagram_xml.encode("utf-8"))
            raw_artifacts.append(
                {
                    "name": f"{_safe_upload_name(title)}.drawio",
                    "path": f"diagram://{diagram_id}",
                    "media_type": "text/html",
                    "size_bytes": size_bytes,
                    "url": _artifact_preview_url(f"diagram://{diagram_id}"),
                }
            )
    if not raw_artifacts:
        stdout_text = str(result.get("stdout") or "")
        for line in stdout_text.splitlines():
            match = _ARTIFACT_LINE_PATTERN.search(line.strip())
            if not match:
                continue
            raw_artifacts.append({"path": match.group(1).strip().strip("'\"")})
    serialized: list[dict] = []
    seen_paths: set[str] = set()
    base_workspace_root = _workspace_root()
    for artifact in raw_artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_path = str(artifact.get("path") or "").strip()
        if not artifact_path:
            continue
        if artifact_path.startswith("diagram://"):
            if artifact_path in seen_paths:
                continue
            media_type = str(artifact.get("media_type") or "text/html").strip() or "text/html"
            serialized.append(
                {
                    "name": artifact.get("name") or "diagram.drawio",
                    "path": artifact_path,
                    "mediaType": media_type,
                    "sizeBytes": artifact.get("size_bytes"),
                    "url": artifact.get("url") or _artifact_preview_url(artifact_path),
                }
            )
            seen_paths.add(artifact_path)
            continue
        candidate = Path(artifact_path).expanduser()
        effective_workspace_root = workspace_root or base_workspace_root
        resolved = candidate.resolve() if candidate.is_absolute() else (effective_workspace_root / candidate).resolve()
        if (
            str(resolved) in seen_paths
            or not any(
                _path_within_root(resolved, root)
                for root in {
                    base_workspace_root,
                    effective_workspace_root.resolve(),
                    _chat_upload_root(),
                    _office_template_upload_root(),
                }
            )
            or not resolved.exists()
            or not resolved.is_file()
        ):
            continue
        media_type = artifact.get("media_type") or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        serialized.append(
            {
                "name": artifact.get("name") or resolved.name,
                "path": str(resolved),
                "mediaType": media_type,
                "sizeBytes": artifact.get("size_bytes") or resolved.stat().st_size,
                "url": _workspace_artifact_url(str(resolved)),
            }
        )
        seen_paths.add(str(resolved))
    return serialized


def _serialize_session_workspace_files(tool_calls: list[ToolCall], *, workspace_root: Path | None = None) -> list[dict]:
    files_by_path: dict[str, dict] = {}
    for tool_call in tool_calls:
        for artifact in _serialize_tool_artifacts(tool_call, workspace_root=workspace_root):
            path = str(artifact.get("path") or "").strip()
            if not path:
                continue
            existing = files_by_path.get(path)
            resolved_path = Path(path).resolve()
            relative_workspace_root = (
                workspace_root if workspace_root and _path_within_root(resolved_path, workspace_root) else None
            )
            payload = _build_workspace_file_payload(
                artifact={
                    **artifact,
                    "url": artifact.get("url") or _workspace_artifact_url(path),
                },
                tool_name=tool_call.tool_name or "",
                created_at=tool_call.created_at,
                workspace_root=relative_workspace_root,
            )
            if existing is None or str(payload["createdAt"] or "") > str(existing.get("createdAt") or ""):
                files_by_path[path] = payload
    return sorted(
        files_by_path.values(),
        key=lambda item: (str(item.get("createdAt") or ""), str(item.get("name") or "").lower()),
        reverse=True,
    )
