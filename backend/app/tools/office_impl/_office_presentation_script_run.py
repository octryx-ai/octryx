"""Build steps of the generated PowerPoint script tool: input checks, script runs and the result."""

from __future__ import annotations

import asyncio
import glob as glob_mod
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.office.slide_checks import slide_gate_check
from ._office_core_helpers import _artifact_for_path, _workspace_root
from ._office_generated_base import run_office_script
from ._office_presentation_script_text import PRESENTATION_SOURCE_INDEX, quality_checked_presentation_slides

ScriptGenerator = Callable[..., str]


@dataclass(frozen=True)
class DeckTarget:
    resolved: Path
    source_potx: Path
    orig_slides: int


@dataclass(frozen=True)
class DeckBuild:
    script_path: Path
    clone_order: list[int]
    slides: list[dict[str, Any]]
    layout_check: dict[str, Any]
    stdout_text: str
    stderr_text: str


def parse_slides_param(params: dict) -> tuple[dict[str, Any] | None, list[Any]]:
    slides = params.get("slides")
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except (json.JSONDecodeError, ValueError):
            return {"error": "slides must be a JSON array of slide objects"}, []
    if not isinstance(slides, list) or not slides:
        return {"error": "slides must be a non-empty list"}, []
    return None, slides


def source_potx_for(detail: dict[str, Any], template_path: Path) -> Path:
    profile_root = str(detail.get("profile_root") or "").strip()
    source_potx: Path | None = None
    if profile_root:
        potx_matches = sorted(glob_mod.glob(str(Path(profile_root) / "source" / "*.potx")))
        if potx_matches:
            source_potx = Path(potx_matches[0])
    if source_potx is None or not source_potx.exists():
        return template_path
    return source_potx


async def _run_script(
    generate: ScriptGenerator, target: DeckTarget, slide_specs: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, Path, list[int], str, str]:
    clone_order: list[int] = []
    for slide in slide_specs:
        if not isinstance(slide, dict):
            continue
        layout = str(slide.get("layout_type") or "").strip()
        clone_order.append(PRESENTATION_SOURCE_INDEX.get(layout, 11))
    script_content = generate(
        source_potx=str(target.source_potx),
        output_pptx=str(target.resolved),
        orig_slides=target.orig_slides,
        clone_order=clone_order,
        slides=slide_specs,
    )
    script_path = target.resolved.parent / (target.resolved.name + ".build.py")
    script_path.write_text(script_content, encoding="utf-8")
    failure, stdout_text, stderr_text = await run_office_script(script_path, timeout_sec=300)
    if failure:
        return failure | {"file_path": str(target.resolved)}, script_path, clone_order, "", ""
    return None, script_path, clone_order, stdout_text, stderr_text


async def build_deck(
    generate: ScriptGenerator, target: DeckTarget, checked_slides: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, DeckBuild | None]:
    failure, script_path, clone_order, stdout_text, stderr_text = await _run_script(generate, target, checked_slides)
    if failure:
        return failure, None
    layout_check = await asyncio.to_thread(slide_gate_check, target.source_potx, target.resolved)
    if layout_check.get("text_fit_findings"):
        aggressive_slides = quality_checked_presentation_slides(checked_slides, aggressive=True)
        if aggressive_slides and aggressive_slides != checked_slides:
            failure, script_path, clone_order, stdout_text, stderr_text = await _run_script(
                generate, target, aggressive_slides
            )
            if failure:
                return failure, None
            checked_slides = aggressive_slides
            layout_check = await asyncio.to_thread(slide_gate_check, target.source_potx, target.resolved)
    return None, DeckBuild(script_path, clone_order, checked_slides, layout_check, stdout_text, stderr_text)


def deck_result(
    context: ToolContext,
    target: DeckTarget,
    build: DeckBuild,
    *,
    detail: dict[str, Any],
    template_source: str,
    source_slide_count: int,
    validation: dict[str, Any],
) -> dict[str, Any]:
    resolved = target.resolved
    result: dict[str, Any] = {
        "success": True,
        "file_path": str(resolved),
        "relative_path": str(resolved.relative_to(_workspace_root(context))),
        "script_path": str(build.script_path),
        "script_relative_path": str(build.script_path.relative_to(_workspace_root(context))),
        "template_path": str(target.source_potx),
        "template_key": (
            f"corp-identity:{detail.get('id')}"
            if template_source == "corp_identity"
            else str(detail.get("id") or "builtin-generic-presentation-template")
        ),
        "template_source": template_source,
        "slide_count": len(build.slides),
        "source_slide_count": source_slide_count,
        "clone_order": build.clone_order,
        "normalized_slides": build.slides,
        "validation": validation,
        "layout_check": build.layout_check,
        "stdout": build.stdout_text,
    }
    if build.stderr_text:
        # Build script stderr is diagnostic text: only its size is kept.
        result["stderr_chars"] = len(build.stderr_text)
    if resolved.exists():
        result["artifacts"] = [_artifact_for_path(context, resolved)]
    return result


__all__ = ["DeckBuild", "DeckTarget", "build_deck", "deck_result", "parse_slides_param", "source_potx_for"]
