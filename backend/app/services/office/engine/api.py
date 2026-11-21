"""The Office engine's operations: what the tools, previews and generated scripts call.

Every operation returns the JSON envelope the Office tools always returned — ``{"success": true, "data": …}`` —
or a closed failure ``{"error": "<code> <fact>", "error_code": "<code>"}``. Mutations write atomically.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import issues as issue_checks
from . import (
    sheets,
    sheets_describe,
    sheets_views,
    slides,
    slides_build,
    slides_describe,
    slides_views,
    word,
    word_views,
    xlsx_extras,
)
from .charts import chart_spec
from .fill import fill_document
from .html import document_html
from .package import (
    document_bytes,
    document_kind,
    existing_file,
    is_template,
    new_document,
    open_document,
    save_document,
)
from .paths import (
    INVALID_REQUEST,
    UNSUPPORTED_ELEMENT,
    OfficeEngineError,
    parse_path,
    parse_selector,
    selector_matches,
)

VIEW_MODES = ("text", "outline", "annotated", "stats", "issues", "html", "forms")
MAX_QUERY_RESULTS = 200


def _closed(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)
        except OfficeEngineError as exc:
            return exc.as_result()

    return wrapper


def _ok(data: Any, message: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"success": True, "data": data}
    if message:
        result["message"] = message
    return result


class Opened:
    """One loaded document; ``save`` writes it back (with the workbook's sparklines carried over)."""

    def __init__(self, path: str | Path) -> None:
        self.path = existing_file(path)
        self.kind = document_kind(self.path)
        self.document = open_document(self.path, self.kind)
        self.sparklines: dict[str, list[str]] = (
            xlsx_extras.read_sparklines(document_bytes(self.path)) if self.kind == "xlsx" else {}
        )

    def save(self, target: str | Path | None = None) -> Path:
        written = save_document(self.document, target or self.path)
        if self.kind == "xlsx":
            xlsx_extras.write_sparklines(written, self.sparklines)
        return written


def _node(opened: Opened, element_path: str) -> Any:
    if opened.kind == "docx":
        return word.resolve(opened.document, parse_path(element_path))
    if opened.kind == "pptx":
        return slides.resolve(opened.document, parse_path(element_path))
    return sheets.resolve(opened.document, element_path)


def _describe(opened: Opened, node: Any, depth: int) -> dict[str, Any]:
    module = {"docx": word, "pptx": slides_describe, "xlsx": sheets_describe}[opened.kind]
    return module.describe(node, depth)


@_closed
def create(path: str | Path, doc_type: str = "") -> dict[str, Any]:
    target = Path(path)
    kind = document_kind(target, doc_type)
    save_document(new_document(kind), target)
    return _ok({"path": str(target), "type": kind}, f"Created {target.name}")


@_closed
def merge(template: str | Path, output: str | Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy ``template`` to ``output`` (a template type becomes its document type) and fill placeholders."""
    source = existing_file(template)
    kind = document_kind(source)
    if document_kind(output) != kind:
        raise OfficeEngineError(INVALID_REQUEST, "template and output must be the same Office type")
    opened = Opened(source)
    report = fill_document(kind, opened.document, data or {})
    opened.save(output)
    return _ok({"path": str(output), "type": kind, "converted_from_template": is_template(source), **report},
               f"Filled {report['replaced']} placeholder(s)")


@_closed
def view(path: str | Path, mode: str = "text", *, start: int | None = None, end: int | None = None,
         max_lines: int | None = None, issue_type: str = "", limit: int | None = None) -> dict[str, Any]:
    normalized = str(mode or "text").strip().lower()
    if normalized not in VIEW_MODES:
        raise OfficeEngineError(INVALID_REQUEST, f"view modes: {', '.join(VIEW_MODES)}")
    opened = Opened(path)
    kind, document = opened.kind, opened.document
    window = {"start": start, "end": end, "max_lines": max_lines}
    if normalized == "html":
        return _ok({"html": document_html(kind, document, opened.path.name)})
    if normalized == "issues":
        return _ok(issue_checks.issues_view(kind, document, issue_type=issue_type, limit=limit))
    if normalized == "forms":
        if kind != "docx":
            raise OfficeEngineError(UNSUPPORTED_ELEMENT, "the forms view is for Word documents")
        return _ok(word_views.forms_view(document))
    views = {"docx": word_views, "pptx": slides_views, "xlsx": sheets_views}[kind]
    if normalized == "stats":
        return _ok(views.stats_view(document))
    if normalized == "outline":
        return _ok(views.outline_view(document))
    if normalized == "annotated":
        return _ok(views.annotated_view(document, **window))
    return _ok(views.text_view(document, **window))


@_closed
def get(path: str | Path, element_path: str, depth: int = 2) -> dict[str, Any]:
    opened = Opened(path)
    node = _node(opened, element_path)
    return _ok(_describe(opened, node, max(1, min(int(depth or 1), 6))))


@_closed
def query(path: str | Path, selector: str) -> dict[str, Any]:
    opened = Opened(path)
    parsed = parse_selector(selector)
    module = {"docx": word, "pptx": slides_describe, "xlsx": sheets_describe}[opened.kind]
    matches = [item for item in module.iter_descriptors(opened.document) if selector_matches(parsed, item)]
    return _ok({"count": len(matches), "results": matches[:MAX_QUERY_RESULTS], "truncated": len(matches) > MAX_QUERY_RESULTS})


@_closed
def set_properties(path: str | Path, element_path: str, props: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(props, dict) or not props:
        raise OfficeEngineError(INVALID_REQUEST, "properties object is required")
    opened = Opened(path)
    node = _node(opened, element_path)
    if opened.kind == "docx":
        word.set_props(opened.document, node, props)
    elif opened.kind == "pptx":
        slides.set_props(node, props)
    else:
        sheets.set_props(opened.document, node, props)
    opened.save()
    return _ok({"path": element_path, "properties": sorted(props)}, f"Updated {element_path}")


def _add_xlsx(opened: Opened, parent: Any, kind: str, props: dict[str, Any], index: int | None) -> tuple[str, dict[str, Any]]:
    workbook = opened.document
    if kind == "sheet":
        worksheet = sheets.add_sheet(workbook, str(props.get("name") or ""), index)
        return f"/{worksheet.title}", {}
    if parent.kind != "sheet":
        raise OfficeEngineError(INVALID_REQUEST, "workbook elements are added to a /<sheet> path")
    worksheet = parent.obj
    if kind == "row":
        values = props.get("values") if isinstance(props.get("values"), list) else []
        sheets.add_row(worksheet, values, index)
        return f"{parent.path}/row[{index or worksheet.max_row}]", {}
    if kind == "chart":
        details = xlsx_extras.add_chart(workbook, worksheet, chart_spec(props), props)
        return f"{parent.path}/chart[{len(worksheet._charts)}]", details
    if kind == "validation":
        xlsx_extras.add_validation(worksheet, props)
    elif kind in {"cf", "conditional_format"}:
        xlsx_extras.add_conditional_format(worksheet, props)
    elif kind == "autofilter":
        xlsx_extras.set_autofilter(worksheet, str(props.get("range") or props.get("ref") or ""))
    elif kind == "sparkline":
        opened.sparklines.setdefault(worksheet.title, []).append(xlsx_extras.sparkline_group(worksheet.title, props))
    elif kind in {"pivottable", "pivot_table"}:
        return parent.path, xlsx_extras.pivot_summary(workbook, worksheet, props)
    else:
        raise OfficeEngineError(
            UNSUPPORTED_ELEMENT,
            "Excel supports: sheet, row, chart, validation, cf, autofilter, sparkline, pivot_table",
        )
    return parent.path, {}


@_closed
def add(path: str | Path, parent_path: str, element_type: str, props: dict[str, Any] | None = None, *,
        from_path: str = "", index: int | None = None) -> dict[str, Any]:
    opened = Opened(path)
    props = dict(props or {})
    kind = str(element_type or "").strip().lower()
    parent = _node(opened, parent_path)
    details: dict[str, Any] = {}
    if opened.kind == "docx":
        new_path = word.add(opened.document, parent, kind, props, index)
    elif opened.kind == "pptx":
        source = None
        if from_path:
            source_node = slides.resolve(opened.document, parse_path(from_path))
            if source_node.kind != "slide":
                raise OfficeEngineError(INVALID_REQUEST, "from_path must address a slide")
            source = source_node.obj
        new_path = slides_build.add(opened.document, parent, kind, props, from_slide=source, index=index)
    else:
        new_path, details = _add_xlsx(opened, parent, kind, props, index)
    opened.save()
    return _ok({"added": kind, "path": new_path, **details}, f"Added {kind} at {new_path}")


@_closed
def remove(path: str | Path, element_path: str) -> dict[str, Any]:
    opened = Opened(path)
    node = _node(opened, element_path)
    if opened.kind == "docx":
        word.remove(node)
    elif opened.kind == "pptx":
        slides.remove(opened.document, node)
    else:
        sheets.remove(opened.document, node)
    opened.save()
    return _ok({"removed": element_path}, f"Removed {element_path}")


@_closed
def validate(path: str | Path) -> dict[str, Any]:
    """The package opens with its library (else ``office_document_unreadable``) and has no ``error`` issue."""
    opened = Opened(path)
    found = issue_checks.document_issues(opened.kind, opened.document)
    errors = [item for item in found if item["severity"] == "error"]
    return _ok({
        "valid": not errors,
        "issue_count": len(found),
        "error_count": len(errors),
        "issues": found[:50],
    })


__all__ = ["VIEW_MODES", "Opened", "add", "create", "get", "merge", "query", "remove", "set_properties", "validate", "view"]
