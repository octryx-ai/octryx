"""Core template block for generated Word scripts."""

from __future__ import annotations

from ._office_word_script_template_citations import (
    _word_script_inline_citations,
    _word_script_reference_entry_ieee_apa,
    _word_script_reference_entry_mla_chicago,
    _word_script_render_bibliography,
)


def _word_script_header(
    *,
    import_root: str,
    template_path: str,
    output_path: str,
    template_data_literal: str,
    sections_literal: str,
    citation_style: str,
    sources_literal: str,
    include_bibliography: bool,
) -> str:
    return f"""\
#!/usr/bin/env python3
\"\"\"Generated Word build script: python-docx plus the platform's Office engine helpers.

Edit and re-run with the backend interpreter to adjust content or layout.
\"\"\"
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.path.append({repr(str(import_root))})  # after the libraries: the engine never shadows them

from docx import Document  # noqa: E402

from app.services.office.engine import word_blocks as blocks  # noqa: E402
from app.services.office.engine.charts import add_docx_chart, chart_spec  # noqa: E402
from app.services.office.engine.diagrams import flow_png, flow_steps  # noqa: E402
from app.services.office.engine.fill import fill_word  # noqa: E402
from app.services.office.engine.package import document_bytes, save_document  # noqa: E402
from app.services.office.engine.paths import OfficeEngineError, length_emu  # noqa: E402

TEMPLATE_PATH = {repr(template_path)}
OUTPUT = Path({repr(output_path)})
TEMPLATE_DATA = json.loads({template_data_literal})
SECTIONS = json.loads({sections_literal})
CITATION_STYLE = {repr(citation_style)}
SOURCES = json.loads({sources_literal})
INCLUDE_BIBLIOGRAPHY = {repr(include_bibliography)}


"""


def _word_script_document_setup() -> str:
    return """\
def open_document():
    \"\"\"The template (its {{placeholders}} filled, styles kept) or a blank document.\"\"\"
    if TEMPLATE_PATH:
        document = Document(io.BytesIO(document_bytes(TEMPLATE_PATH)))
        report = fill_word(document, TEMPLATE_DATA)
        print(f"template filled: {report['replaced']} placeholder(s), missing {report['missing']}")
        return document
    return Document()


DOC = open_document()


def add_paragraph(text: str, *, style: str = "", alignment: str = "") -> None:
    props = {"alignment": alignment} if alignment else {}
    if style and blocks.style_or_none(DOC, style) is not None:
        props["style"] = style
    blocks.add_paragraph(DOC, DOC, text, **props)


def add_heading(text: str, level: int, *, alignment: str = "") -> None:
    blocks.add_heading(DOC, DOC, text, level, **({"alignment": alignment} if alignment else {}))


"""


def _word_script_text_and_author_helpers() -> str:
    return """\
def add_equation(formula: str) -> None:
    blocks.add_equation(DOC, formula)


def add_toc(*, title: str = "Table of Contents", levels: str = "1-3") -> None:
    blocks.add_toc(DOC, DOC, title=title, levels=levels)


def text_lines(value: object) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(line).strip() for line in value if str(line).strip()]
    return []


def _clean_key(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text


def _year_for_source(source: dict[str, object]) -> str:
    for key in ("year", "published_year", "published_at", "date", "accessed_at"):
        value = str(source.get(key) or "").strip()
        if not value:
            continue
        match = re.search(r"(19|20)\\d{2}", value)
        if match:
            return match.group(0)
    return "n.d."


def _author_tokens(source: dict[str, object]) -> list[str]:
    authors = source.get("authors")
    if isinstance(authors, list):
        values = [str(item).strip() for item in authors if str(item).strip()]
        if values:
            return values
    author = str(source.get("author") or "").strip()
    return [author] if author else []


def _author_label(source: dict[str, object]) -> str:
    authors = _author_tokens(source)
    if not authors:
        return str(source.get("publisher") or source.get("organization") or source.get("title") or "Source").strip()
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return f"{authors[0]} et al."


"""


def _word_script_source_index() -> str:
    return """\
def _author_surname(source: dict[str, object]) -> str:
    label = _author_label(source).strip()
    if not label:
        return "Source"
    parts = [part for part in re.split(r"\\s+", label) if part]
    return parts[-1].strip(",.") if parts else label


def _source_title(source: dict[str, object]) -> str:
    return str(source.get("title") or source.get("name") or source.get("url") or "Untitled source").strip()


def _source_url(source: dict[str, object]) -> str:
    return str(source.get("url") or source.get("link") or "").strip()


def _accessed_at(source: dict[str, object]) -> str:
    return str(source.get("accessed_at") or source.get("accessed") or "").strip()


def _source_doi(source: dict[str, object]) -> str:
    return str(source.get("doi") or "").strip()


def _source_isbn(source: dict[str, object]) -> str:
    return str(source.get("isbn") or "").strip()


def _build_source_index() -> tuple[list[dict[str, object]], dict[str, int]]:
    normalized: list[dict[str, object]] = []
    index: dict[str, int] = {}
    for position, raw_source in enumerate(SOURCES, start=1):
        if not isinstance(raw_source, dict):
            continue
        source = dict(raw_source)
        normalized.append(source)
        keys = [
            str(source.get("id") or "").strip(),
            str(source.get("key") or "").strip(),
            _source_url(source),
            _source_title(source),
        ]
        for key in keys:
            cleaned = _clean_key(key)
            if cleaned and cleaned not in index:
                index[cleaned] = position
    return normalized, index


NORMALIZED_SOURCES, SOURCE_INDEX = _build_source_index()


"""


def render_word_script_template_core(
    *,
    import_root: str,
    template_path: str,
    output_path: str,
    template_data_literal: str,
    sections_literal: str,
    citation_style: str,
    sources_literal: str,
    include_bibliography: bool,
) -> str:
    return (
        _word_script_header(
            import_root=import_root,
            template_path=template_path,
            output_path=output_path,
            template_data_literal=template_data_literal,
            sections_literal=sections_literal,
            citation_style=citation_style,
            sources_literal=sources_literal,
            include_bibliography=include_bibliography,
        )
        + _word_script_document_setup()
        + _word_script_text_and_author_helpers()
        + _word_script_source_index()
        + _word_script_inline_citations()
        + _word_script_reference_entry_ieee_apa()
        + _word_script_reference_entry_mla_chicago()
        + _word_script_render_bibliography()
    )


__all__ = ["render_word_script_template_core"]
