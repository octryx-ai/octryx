"""Call extractors (Python AST and per-language regex) for the native Code Graph."""

from __future__ import annotations

import ast
import re
from typing import Any

from app.services.code_intelligence.graph_primitives import CALL_KEYWORDS


def _extract_python_calls(
    *, relative_path: str, text: str, symbol_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text, filename=relative_path)
    except SyntaxError:
        return []
    symbol_ranges = _symbol_ranges(symbol_by_id, relative_path)
    calls: list[dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> Any:
            source = _source_symbol_for_line(symbol_ranges, int(getattr(node, "lineno", 0) or 0))
            target = _python_call_name(node.func)
            if source and target and target not in CALL_KEYWORDS:
                calls.append(
                    {
                        "source": source,
                        "target": target,
                        "line": int(getattr(node, "lineno", 0) or 0),
                        "extractor": "python_ast",
                    }
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return calls


def _extract_regex_calls(
    *, relative_path: str, text: str, symbol_by_id: dict[str, dict[str, Any]], language: str
) -> list[dict[str, Any]]:
    symbol_ranges = _symbol_ranges(symbol_by_id, relative_path)
    calls: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        source = _source_symbol_for_line(symbol_ranges, line_no)
        if not source:
            continue
        for target in re.findall(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", line):
            if target in CALL_KEYWORDS:
                continue
            calls.append({"source": source, "target": target, "line": line_no, "extractor": f"{language}_regex"})
    return calls


def _symbol_ranges(symbol_by_id: dict[str, dict[str, Any]], relative_path: str) -> list[tuple[int, int, str]]:
    rows = []
    for symbol in symbol_by_id.values():
        if str(symbol.get("path") or "") != relative_path:
            continue
        start = int(symbol.get("line") or 0)
        end = int(symbol.get("line_end") or start or 0)
        rows.append((start, max(start, end), str(symbol.get("id") or "")))
    return sorted(rows, key=lambda item: (item[1] - item[0], item[0]))


def _source_symbol_for_line(ranges: list[tuple[int, int, str]], line: int) -> str:
    for start, end, node_id in ranges:
        if start <= line <= end:
            return node_id
    return ""


def _python_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
