"""Deterministic Word composition from an evidence-bound document plan.

The mirror of ``presentation_composer``: it opens the corporate template so the
document inherits the template's styles, theme, headers and footers, clears the
template's sample body, and writes the planned sections using the template's own
named styles (resolved through the style snapshot's role map). It never invents
formatting and never writes a claim the plan did not carry a source for — every
section states its evidence, and the missing 20% stays visible as markers and an
open-points section, exactly as the deck composer does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Emu

from ..error_facts import error_type
from .document_snapshot import style_for_role


class DocumentComposerError(RuntimeError):
    """Composition failed in a way the caller must surface, never swallow."""


_SOURCE_PREFIX = "Source: "
_MAX_IMAGE_WIDTH_EMU = 6_400_000  # ~6.67 in; fits inside 1-inch margins on Letter/A4


def _clear_body(document: Document) -> None:
    """Remove the template's sample body content, keeping the section setup.

    Everything the template ships in the document body — paragraphs, tables, and
    the content controls (``w:sdt``) that carry cover titles and tables of
    contents — is sample content, not corporate identity. The identity lives in
    separate parts (theme, styles, header/footer, logo media) that are untouched.
    Only the body-level ``w:sectPr`` (page size, margins, and the header/footer
    references) is kept, so the letterhead, logo and footer survive while the
    template's placeholder text does not leak into the composed document.
    """
    body = document.element.body
    for child in list(body):
        if child.tag.endswith("}sectPr"):
            continue
        body.remove(child)


def _add_source(document: Document, snapshot: dict[str, Any], source: str) -> None:
    source = str(source or "").strip()
    if not source:
        return
    caption_style = style_for_role(snapshot, "caption", default=style_for_role(snapshot, "body"))
    paragraph = document.add_paragraph(style=caption_style)
    run = paragraph.add_run(f"{_SOURCE_PREFIX}{source}")
    run.italic = True


def _add_heading(document: Document, snapshot: dict[str, Any], level: int, text: str) -> None:
    role = f"heading{max(1, min(4, int(level or 1)))}"
    style = style_for_role(snapshot, role, default=style_for_role(snapshot, "heading1", default="Normal"))
    document.add_paragraph(str(text or ""), style=style)


def _add_image(document: Document, path: str) -> bool:
    image_path = Path(str(path or ""))
    if not image_path.is_file():
        return False
    try:
        document.add_picture(str(image_path), width=Emu(_MAX_IMAGE_WIDTH_EMU))
        return True
    except Exception:  # python-docx raises bare exceptions on unreadable images
        return False


def _open_template(template: Path) -> Any:
    if not template.is_file():
        raise DocumentComposerError(f"template not found: {template.name}")
    try:
        return Document(str(template))
    except Exception as exc:
        raise DocumentComposerError(f"template could not be opened (error_type={error_type(exc)})") from exc


def _add_title(
    document: Document, snapshot: dict[str, Any], block: dict[str, Any], body_style: str, source: str
) -> None:
    style = style_for_role(snapshot, "title", default=style_for_role(snapshot, "heading1", default="Normal"))
    document.add_paragraph(str(block.get("text") or ""), style=style)
    subtitle = str(block.get("subtitle") or "").strip()
    if subtitle:
        document.add_paragraph(subtitle, style=style_for_role(snapshot, "subtitle", default=body_style))
    _add_source(document, snapshot, source)


def _add_diagram(
    document: Document,
    snapshot: dict[str, Any],
    block: dict[str, Any],
    source: str,
    findings: list[dict[str, Any]],
) -> int:
    """Write a diagram block; returns how many images were embedded (0 or 1)."""
    title = str(block.get("title") or "").strip()
    if title:
        _add_heading(document, snapshot, int(block.get("level") or 2), title)
    if _add_image(document, str(block.get("image") or "")):
        _add_source(document, snapshot, source or f"Diagram {title}")
        return 1
    findings.append(
        {
            "rule": "diagram_missing",
            "severity": "warning",
            "message": f"diagram image not embedded: {title}",
        }
    )
    return 0


def _write_block(
    document: Document,
    snapshot: dict[str, Any],
    block: dict[str, Any],
    styles: tuple[str, str],
    findings: list[dict[str, Any]],
) -> tuple[bool, int]:
    """Write one plan block; returns whether it was written and how many images it embedded."""
    body_style, bullet_style = styles
    kind = str(block.get("kind") or "").strip()
    source = str(block.get("source") or "").strip()
    if kind == "title":
        _add_title(document, snapshot, block, body_style, source)
    elif kind == "heading":
        _add_heading(document, snapshot, int(block.get("level") or 1), str(block.get("text") or ""))
        _add_source(document, snapshot, source)
    elif kind == "paragraph":
        document.add_paragraph(str(block.get("text") or ""), style=body_style)
    elif kind == "bullets":
        for item in block.get("items") or []:
            text = item.get("text") if isinstance(item, dict) else item
            document.add_paragraph(str(text or ""), style=bullet_style)
    elif kind == "marker":
        paragraph = document.add_paragraph(style=body_style)
        run = paragraph.add_run(str(block.get("text") or ""))
        run.bold = True
    elif kind == "diagram":
        return True, _add_diagram(document, snapshot, block, source, findings)
    else:
        # Unknown block kinds are dropped rather than approximated.
        return False, 0
    return True, 0


def build_document_from_plan(
    template_path: str | Path,
    snapshot: dict[str, Any],
    plan: list[dict[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    """Compose the document and return what was written, for the gate and audit."""
    document = _open_template(Path(template_path))

    _clear_body(document)

    body_style = style_for_role(snapshot, "body", default="Normal")
    bullet_style = style_for_role(snapshot, "list_bullet", default=body_style)
    section_roles: list[str] = []
    findings: list[dict[str, Any]] = []
    images_embedded = 0

    for block in plan:
        if not isinstance(block, dict):
            continue
        written, embedded = _write_block(document, snapshot, block, (body_style, bullet_style), findings)
        images_embedded += embedded
        if not written:
            continue
        kind = str(block.get("kind") or "").strip()
        role_label = kind if kind != "heading" else f"heading{block.get('level') or 1}"
        section_roles.append(role_label)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        document.save(str(output))
    except Exception as exc:
        raise DocumentComposerError(f"document could not be saved (error_type={error_type(exc)})") from exc

    return {
        "output_path": str(output),
        "block_count": len(section_roles),
        "section_roles": section_roles,
        "images_embedded": images_embedded,
        "quality_findings": findings,
    }


__all__ = ["build_document_from_plan", "DocumentComposerError"]
