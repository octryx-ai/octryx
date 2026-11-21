"""Deterministic presentation composition from turn evidence.

``create_presentation`` is the only sanctioned way to produce a slide deck: it
takes the corporate template's layout catalog, the evidence the turn already
collected (AWS topology snapshot, optional knowledge facts, diagrams from our
own pipeline), plans the slides deterministically, composes the deck from the
template's own layouts, and runs the slide gate on the result.

It never invents evidence. Without an ``aws_topology_snapshot`` in the turn it
returns an error naming the tool that must run first, rather than writing a
deck of plausible-sounding claims.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .context import ToolContext
from .presentation_impl._presentation_evidence import (
    AWS_SNAPSHOT_TOOL,
    aws_snapshot_from_history,
    diagram_images_from_history,
    externalized_snapshot_artifact_id,
    knowledge_facts_from_history,
    load_snapshot_artifact,
    snapshot_is_usable,
)
from .presentation_impl._presentation_evidence import MAX_DIAGRAM_IMAGES as _MAX_DIAGRAM_IMAGES
from .presentation_impl._presentation_template import TemplateResolutionError, resolve_composer_template

_logger = logging.getLogger("uvicorn.error")

_OUTPUT_DIR = "presentations"
_ASSET_DIR = "assets"
_MIN_SLIDES = 2
_MAX_SLIDES = 40
_DEFAULT_SLUG = "presentation"


class CreatePresentationTool:
    name = "create_presentation"
    description = (
        "Compose a brand-compliant, evidence-backed PowerPoint deck from the corporate template and the "
        "evidence already collected in this turn. Requires a prior aws_topology_snapshot; embeds diagrams "
        "created in this turn and knowledge_search facts when present."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        topic = str(params.get("topic") or "").strip()
        if not topic:
            return {"error": "topic is required"}

        turn_tool_history = list(getattr(context, "turn_tool_history", None) or [])
        content = _parse_content(params.get("content"))
        aws_snapshot = aws_snapshot_from_history(turn_tool_history)
        if not snapshot_is_usable(aws_snapshot):
            # A large snapshot lives in the artifact store and the turn history
            # keeps only a capped preview; composing from that would produce a
            # silently thin deck, so read the real payload.
            artifact_id = externalized_snapshot_artifact_id(turn_tool_history)
            if artifact_id:
                loaded = await load_snapshot_artifact(context.db, artifact_id)
                if snapshot_is_usable(loaded):
                    aws_snapshot = loaded
        # The deck is composed from an AWS topology snapshot *or* from explicit
        # sourced `content` (any topic). One of the two is required — never
        # invented prose.
        if not aws_snapshot and not content:
            return {
                "error": (
                    f"No {AWS_SNAPSHOT_TOOL} result and no `content` in this turn. The deck is composed from "
                    f"collected evidence — run {AWS_SNAPSHOT_TOOL} first for an architecture deck, or pass "
                    "`content` (title + sourced sections) for any other topic."
                ),
                "required_tool": AWS_SNAPSHOT_TOOL,
                "evidence_sources": [],
            }

        try:
            template_path, template_resolution = await resolve_composer_template(
                context,
                profile_id=str(params.get("profile_id") or ""),
                template_path=str(params.get("template_path") or params.get("template") or ""),
            )
        except TemplateResolutionError as exc:
            return {"status": "needs_configuration", "error": str(exc), "error_code": exc.code}

        max_slides = _bounded_max_slides(params.get("max_slides"))
        output_path = _output_path(context, topic)
        asset_dir = output_path.parent / _ASSET_DIR

        # The deck's diagrams are the full evidence set derived from the
        # snapshot (overview + service inventory + substantive detail views),
        # never however many times the model happened to call create_diagram.
        # If the snapshot carries no diagram_brief, fall back to the diagrams the
        # turn already rendered.
        from .presentation_impl._presentation_diagrams import evidence_diagram_images

        diagram_warnings: list[str] = []
        diagram_images: list[dict[str, str]] = []
        if aws_snapshot:
            diagram_images, diagram_warnings = await evidence_diagram_images(
                aws_snapshot, output_dir=asset_dir, max_images=_MAX_DIAGRAM_IMAGES
            )
        if not diagram_images:
            diagram_images, diagram_warnings = await diagram_images_from_history(
                turn_tool_history,
                output_dir=asset_dir,
                db=context.db,
                session_id=str(getattr(context, "session_id", "") or ""),
            )
        knowledge_facts = knowledge_facts_from_history(turn_tool_history)

        from ..services.office_identity import (
            ComposerError,
            build_aws_deck_plan,
            build_generic_deck_plan,
            build_presentation_from_plan,
            build_template_snapshot,
        )

        try:
            template_snapshot = build_template_snapshot(
                template_path, example_deck_path=template_resolution.get("example_deck_path")
            )
        except (FileNotFoundError, ValueError) as exc:
            return {"error": f"Template '{template_path}' could not be read: {exc}"}

        if content:
            plan = build_generic_deck_plan(
                content, template_snapshot, diagram_images=diagram_images or None
            )
        else:
            plan = build_aws_deck_plan(
                aws_snapshot,
                template_snapshot,
                knowledge_facts=knowledge_facts or None,
                diagram_images=diagram_images or None,
            )
        plan, trimmed = _apply_max_slides(plan, max_slides)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            composed = build_presentation_from_plan(template_path, template_snapshot, plan, output_path)
        except ComposerError as exc:
            return {"error": f"Deck composition failed: {exc}"}

        quality_findings = list(composed.get("quality_findings") or [])
        warnings = list(diagram_warnings)
        if trimmed:
            warnings.append(f"plan trimmed to max_slides={max_slides}: {trimmed} slide(s) omitted")

        from .office_impl._office_core_helpers import _artifact_for_path

        result: dict[str, Any] = {
            "status": "created",
            "topic": topic,
            "file_path": str(output_path),
            "slide_count": composed.get("slide_count"),
            "slides": [
                {
                    "index": index + 1,
                    "title": str(entry.get("title") or ""),
                    "layout_key": layout_key,
                }
                for index, (entry, layout_key) in enumerate(
                    zip(plan, list(composed.get("layout_keys") or []) + [""] * len(plan), strict=False)
                )
            ],
            "quality_findings": quality_findings,
            "quality_warning_count": sum(
                1 for finding in quality_findings if str(finding.get("severity") or "") == "warning"
            ),
            "evidence_sources": _evidence_sources(
                aws_snapshot=aws_snapshot,
                knowledge_facts=knowledge_facts,
                diagram_images=diagram_images,
                content=content,
            ),
            "template": template_resolution,
            "warnings": warnings,
        }
        # Gate warnings are the human's remaining 20%: never silently swallowed.
        if result["quality_warning_count"]:
            result["message"] = (
                f"Deck composed with {result['quality_warning_count']} quality warning(s) — "
                "review quality_findings before sharing."
            )
        else:
            result["message"] = "Deck composed; slide gate reported no warnings."

        if output_path.exists():
            result["artifacts"] = [_artifact_for_path(context, output_path)]
        _logger.info(
            "create_presentation: slides=%s findings=%d diagrams=%d facts=%d",
            result.get("slide_count"),
            len(quality_findings),
            len(diagram_images),
            len(knowledge_facts),
        )
        return result

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False


def _parse_content(raw: Any) -> dict[str, Any]:
    """Normalise the optional ``content`` param to a sections-bearing dict.

    Accepts a dict or a JSON string; returns ``{}`` when there is nothing usable,
    so the AWS-snapshot path stays the default.
    """
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    sections = [section for section in (raw.get("sections") or []) if isinstance(section, dict)]
    if not sections and not str(raw.get("title") or "").strip():
        return {}
    return raw


def _bounded_max_slides(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _MAX_SLIDES
    return max(_MIN_SLIDES, min(_MAX_SLIDES, value))


def _apply_max_slides(plan: list[dict[str, Any]], max_slides: int) -> tuple[list[dict[str, Any]], int]:
    """Trim the plan while keeping the closing open-points slide.

    The open points are the deck's honesty ledger; dropping them to satisfy a
    slide budget would hide exactly what must stay visible.
    """
    if len(plan) <= max_slides:
        return plan, 0
    trimmed = len(plan) - max_slides
    return [*plan[: max_slides - 1], plan[-1]], trimmed


def _evidence_sources(
    *,
    aws_snapshot: dict[str, Any],
    knowledge_facts: list[dict[str, str]],
    diagram_images: list[dict[str, str]],
    content: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if aws_snapshot:
        sources.append(
            {
                "kind": AWS_SNAPSHOT_TOOL,
                "account_id": str(aws_snapshot.get("account_id") or ""),
                "generated_at": str(aws_snapshot.get("generated_at") or ""),
            }
        )
    if content:
        sources.append(
            {
                "kind": "content",
                "title": str(content.get("title") or ""),
                "section_count": len(content.get("sections") or []),
            }
        )
    if knowledge_facts:
        sources.append(
            {
                "kind": "knowledge_search",
                "fact_count": len(knowledge_facts),
                "keys": [fact["source"] for fact in knowledge_facts],
            }
        )
    if diagram_images:
        sources.append(
            {
                "kind": "diagram",
                "diagram_ids": [image.get("diagram_id", "") for image in diagram_images],
            }
        )
    return sources


def _output_path(context: ToolContext, topic: str) -> Path:
    from .office_impl._office_core_helpers import _resolve_path

    return _resolve_path(context, f"{_OUTPUT_DIR}/{_slug(topic)}.pptx")


def _slug(topic: str) -> str:
    lowered = topic.strip().lower()
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return (slug[:60].rstrip("-")) or _DEFAULT_SLUG
