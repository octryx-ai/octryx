"""Output preparation and script run shared by the generated Word and Excel script tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.office.engine.package import is_template
from app.tools.context import ToolContext

from ._office_core_helpers import (
    _artifact_for_path,
    _resolve_path,
    _resolve_template_for_output,
    _template_path_refusal,
    _workspace_root,
)
from ._office_generated_base import _GeneratedOfficeScriptToolBase


@dataclass(frozen=True)
class GeneratedOutput:
    resolved: Path
    template_resolved: Path | None
    template_entry: dict[str, Any] | None


async def prepare_generated_output(
    context: ToolContext,
    *,
    file_path: str,
    template_key: str,
    template_path: str,
    doc_type: str,
) -> tuple[dict[str, Any] | None, GeneratedOutput | None]:
    refusal = _template_path_refusal(context, template_path)
    if refusal:
        return refusal, None
    resolved = _resolve_path(context, file_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    template_resolved: Path | None = None
    template_entry: dict[str, Any] | None = None
    try:
        template_resolved, template_entry = await _resolve_template_for_output(
            context,
            template_key=template_key,
            template_path=template_path,
            doc_type=doc_type,
        )
    except FileNotFoundError:
        template_resolved = None
        template_entry = None
    return None, GeneratedOutput(resolved, template_resolved, template_entry)


async def run_generated_script(
    tool: _GeneratedOfficeScriptToolBase,
    context: ToolContext,
    output: GeneratedOutput,
    *,
    script_content: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    resolved = output.resolved
    template_resolved = output.template_resolved
    script_path = tool._write_script(resolved, script_content)
    error, stdout_text, stderr_text = await tool._execute_script(script_path)
    if error:
        error["file_path"] = str(resolved)
        return error

    normalized_document_type = bool(template_resolved) and is_template(template_resolved)
    validation = await tool._validate_document(resolved)
    stats = await tool._inspect_document_stats(resolved)

    result: dict[str, Any] = {
        "success": True,
        "file_path": str(resolved),
        "relative_path": str(resolved.relative_to(_workspace_root(context))),
        "script_path": str(script_path),
        "script_relative_path": str(script_path.relative_to(_workspace_root(context))),
        "template_path": str(template_resolved) if template_resolved else "",
        **details,
        "validation": validation,
        "stats": stats,
        "normalized_document_type": normalized_document_type,
        "stdout": stdout_text,
    }
    if output.template_entry:
        result["template_key"] = str(output.template_entry.get("key") or "")
    if stderr_text:
        # Build script stderr is diagnostic text: only its size is kept.
        result["stderr_chars"] = len(stderr_text)
    if resolved.exists():
        result["artifacts"] = [_artifact_for_path(context, resolved)]
    return result


__all__ = ["GeneratedOutput", "prepare_generated_output", "run_generated_script"]
