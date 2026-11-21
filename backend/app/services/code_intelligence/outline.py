"""Outline and tree-sitter helpers for code intelligence."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from app.services.code_intelligence.process import _run_command
from app.services.code_intelligence.storage_capabilities import _find_binary
from app.services.code_intelligence.storage_runtime import _truncate
from app.services.process_output_redaction import redact_process_output


def _outline_from_symbols(*, symbols: list[dict[str, Any]], file_path: str) -> list[dict[str, Any]]:
    file_symbols = [item for item in symbols if str(item.get("path") or "") == file_path]
    return [
        {
            "name": str(item.get("name") or ""),
            "kind": str(item.get("kind") or "symbol"),
            "line": int(item.get("line") or 1),
            "end_line": int(item.get("line") or 1),
            "language": str(item.get("language") or ""),
            "signature": str(item.get("signature") or ""),
            "backend": "regex",
        }
        for item in sorted(file_symbols, key=lambda row: (int(row.get("line") or 1), str(row.get("name") or "")))
    ]


def _python_ast_outline(file_path: Path, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text, filename=str(file_path))
    except SyntaxError:
        return []

    nodes: list[dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[str] = []

        def _push(self, *, node: ast.AST, kind: str, name: str) -> None:
            start = int(getattr(node, "lineno", 1) or 1)
            end = int(getattr(node, "end_lineno", start) or start)
            signature = name
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signature = f"{name}({', '.join(arg.arg for arg in node.args.args)})"
            nodes.append(
                {
                    "name": name,
                    "kind": kind,
                    "line": start,
                    "end_line": end,
                    "language": "python",
                    "signature": signature,
                    "parents": list(self.parents),
                    "backend": "python_ast",
                }
            )

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            self._push(node=node, kind="class", name=node.name)
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self._push(node=node, kind="function", name=node.name)
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            self._push(node=node, kind="async_function", name=node.name)
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

    Visitor().visit(tree)
    return nodes

async def _tree_sitter_outline(file_path: Path) -> dict[str, Any] | None:
    binary = _find_binary("tree-sitter")
    if not binary:
        return None
    result = await _run_command([binary, "parse", str(file_path)], cwd=file_path.parent, timeout_sec=60)
    if result["exit_code"] != 0:
        # Parser stderr is diagnostics only: closed code and exit status.
        return {
            "backend": "tree-sitter",
            "status": "error",
            "raw_tree": "",
            "error_code": "tree_sitter_parse_failed",
            "exit_code": result["exit_code"],
        }
    # The parse tree is the outline result the agent reads: kept, through the redactor.
    return {
        "backend": "tree-sitter",
        "status": "ready",
        "raw_tree": _truncate(redact_process_output(result["stdout"]), max_chars=4000),
    }
