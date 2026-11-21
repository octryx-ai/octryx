"""Deterministic Word document composition from turn evidence.

``create_document`` is the document mirror of ``create_presentation``: it takes
the corporate Word template's style catalog, the evidence the turn already
collected (AWS topology snapshot, optional knowledge facts, diagrams from our own
pipeline), plans the sections deterministically, composes the document from the
template's own styles, and never invents a claim without a source. A profile may
hold several Word templates for different purposes; the right one is chosen
explicitly, and when several exist and none was named the tool returns the
catalog so the caller picks a purpose rather than the tool guessing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .context import ToolContext
from .document_impl._document_template import DocumentTemplateError, resolve_document_template
from .presentation_impl._presentation_diagrams import evidence_diagram_images
from .presentation_impl._presentation_evidence import (
    AWS_SNAPSHOT_TOOL,
    MAX_DIAGRAM_IMAGES,
    aws_snapshot_from_history,
    diagram_images_from_history,
    externalized_snapshot_artifact_id,
    knowledge_facts_from_history,
    load_snapshot_artifact,
    snapshot_is_usable,
)

_logger = logging.getLogger("uvicorn.error")

_OUTPUT_DIR = "documents"
_ASSET_DIR = "assets"
_DEFAULT_SLUG = "document"


class CreateDocumentTool:
    name = "create_document"
    description = (
        "Compose a brand-compliant, evidence-backed Word document from the corporate template and the "
        "evidence already collected in this turn. Requires a prior aws_topology_snapshot; embeds diagrams "
        "from our own pipeline and knowledge_search facts when present. When the profile has several Word "
        "templates for different purposes, pass `template` to choose one; otherwise the tool returns the catalog."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        topic = str(params.get("topic") or "").strip()
        if not topic:
            return {"error": "topic is required"}

        turn_tool_history = list(getattr(context, "turn_tool_history", None) or [])
        content = _parse_content(params.get("content"))
        aws_snapshot = aws_snapshot_from_history(turn_tool_history)
        if not snapshot_is_usable(aws_snapshot):
            artifact_id = externalized_snapshot_artifact_id(turn_tool_history)
            if artifact_id:
                loaded = await load_snapshot_artifact(context.db, artifact_id)
                if snapshot_is_usable(loaded):
                    aws_snapshot = loaded
        if not aws_snapshot and not content:
            return {
                "error": (
                    f"No {AWS_SNAPSHOT_TOOL} result and no `content` in this turn. The document is composed "
                    f"from collected evidence — run {AWS_SNAPSHOT_TOOL} first for an architecture document, or "
                    "pass `content` (title + sourced sections) for any other topic."
                ),
                "required_tool": AWS_SNAPSHOT_TOOL,
                "evidence_sources": [],
            }

        try:
            choice = await resolve_document_template(
                context,
                profile_id=str(params.get("profile_id") or ""),
                template_path=str(params.get("template_path") or params.get("template_file") or ""),
                template=str(params.get("template") or ""),
            )
        except DocumentTemplateError as exc:
            return {"error": str(exc)}

        if choice.needs_selection or choice.path is None:
            return {
                "status": "needs_template_selection",
                "message": (
                    "This profile has several Word templates for different purposes. Call create_document "
                    "again with `template` set to the template_id or name that fits this document."
                ),
                "templates": choice.catalog,
                "profile": choice.resolution,
            }

        template_path = choice.path
        output_path = _output_path(context, topic)
        asset_dir = output_path.parent / _ASSET_DIR

        diagram_warnings: list[str] = []
        diagram_images: list[dict[str, str]] = []
        if aws_snapshot:
            diagram_images, diagram_warnings = await evidence_diagram_images(
                aws_snapshot, output_dir=asset_dir, max_images=MAX_DIAGRAM_IMAGES
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
            DocumentComposerError,
            build_aws_document_plan,
            build_document_from_plan,
            build_document_snapshot,
            build_generic_document_plan,
            check_document_quality,
        )

        try:
            document_snapshot = build_document_snapshot(template_path)
        except (FileNotFoundError, ValueError) as exc:
            return {"error": f"Template '{template_path}' could not be read: {exc}"}

        if content:
            plan = build_generic_document_plan(content, diagram_images=diagram_images or None)
        else:
            plan = build_aws_document_plan(
                aws_snapshot,
                document_snapshot,
                knowledge_facts=knowledge_facts or None,
                diagram_images=diagram_images or None,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            composed = build_document_from_plan(template_path, document_snapshot, plan, output_path)
        except DocumentComposerError as exc:
            return {"error": f"Document composition failed: {exc}"}

        quality_findings = list(composed.get("quality_findings") or [])
        quality_findings.extend(check_document_quality(plan, document_snapshot))
        warnings = list(diagram_warnings)

        from .office_impl._office_core_helpers import _artifact_for_path

        result: dict[str, Any] = {
            "status": "created",
            "topic": topic,
            "file_path": str(output_path),
            "block_count": composed.get("block_count"),
            "images_embedded": composed.get("images_embedded"),
            "quality_findings": quality_findings,
            "quality_warning_count": sum(
                1 for finding in quality_findings if str(finding.get("severity") or "") == "warning"
            ),
            "evidence_sources": _evidence_sources(aws_snapshot, knowledge_facts, diagram_images, content),
            "template": choice.resolution,
            "warnings": warnings,
        }
        result["message"] = (
            f"Document composed with {result['quality_warning_count']} quality warning(s) — review before sharing."
            if result["quality_warning_count"]
            else "Document composed; no quality warnings."
        )
        if output_path.exists():
            result["artifacts"] = [_artifact_for_path(context, output_path)]
        _logger.info(
            "create_document: blocks=%s images=%d facts=%d",
            result.get("block_count"),
            len(diagram_images),
            len(knowledge_facts),
        )
        return result

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False


def _parse_content(raw: Any) -> dict[str, Any]:
    """Normalise the optional ``content`` param (dict or JSON string) to a dict."""
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


def _evidence_sources(
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
        sources.append({"kind": "knowledge_search", "fact_count": len(knowledge_facts)})
    if diagram_images:
        sources.append({"kind": "diagram", "diagram_ids": [i.get("diagram_id", "") for i in diagram_images]})
    return sources


def _output_path(context: ToolContext, topic: str) -> Path:
    from .office_impl._office_core_helpers import _resolve_path

    return _resolve_path(context, f"{_OUTPUT_DIR}/{_slug(topic)}.docx")


def _slug(topic: str) -> str:
    lowered = topic.strip().lower()
    for source, target in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        lowered = lowered.replace(source, target)
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return (slug[:60].rstrip("-")) or _DEFAULT_SLUG
