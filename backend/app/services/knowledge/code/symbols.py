"""Symbol line ranges of a source file, for code-aware chunking."""

from __future__ import annotations

import ast
from dataclasses import dataclass

import tree_sitter_java
from tree_sitter import Language, Node, Parser

_JAVA_CONTAINERS = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    }
)
_JAVA_MEMBERS = frozenset({"method_declaration", "constructor_declaration"})
_JAVA_COMMENTS = frozenset({"block_comment", "line_comment"})
_JAVA = Language(tree_sitter_java.language())
MAX_SYMBOL_DEPTH = 8


@dataclass(frozen=True, slots=True)
class Symbol:
    path: tuple[str, ...]
    line_start: int
    line_end: int


def _name(node: Node, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        return node.type.removesuffix("_declaration")
    return source[name.start_byte : name.end_byte].decode("utf-8", errors="replace")


def _leading_comment_start(node: Node) -> int:
    start = node.start_point[0]
    sibling = node.prev_sibling
    while sibling is not None and sibling.type in _JAVA_COMMENTS and sibling.end_point[0] >= start - 1:
        start = sibling.start_point[0]
        sibling = sibling.prev_sibling
    return start


def java_symbols(text: str) -> tuple[Symbol, ...]:
    source = text.encode("utf-8")
    tree = Parser(_JAVA).parse(source)
    found: list[Symbol] = []

    def visit(node: Node, path: tuple[str, ...]) -> None:
        for child in node.children:
            if child.type in _JAVA_CONTAINERS or child.type in _JAVA_MEMBERS:
                inner = (*path, _name(child, source))
                found.append(Symbol(inner, _leading_comment_start(child) + 1, child.end_point[0] + 1))
                if child.type in _JAVA_CONTAINERS and len(inner) < MAX_SYMBOL_DEPTH:
                    body = child.child_by_field_name("body")
                    if body is not None:
                        visit(body, inner)
            elif child.type in ("program", "class_body"):
                visit(child, path)

    visit(tree.root_node, ())
    return tuple(found)


def python_symbols(text: str) -> tuple[Symbol, ...]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return ()
    found: list[Symbol] = []

    def visit(body: list[ast.stmt], path: tuple[str, ...]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                inner = (*path, node.name)
                start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
                found.append(Symbol(inner, start, int(node.end_lineno or node.lineno)))
                if isinstance(node, ast.ClassDef) and len(inner) < MAX_SYMBOL_DEPTH:
                    visit(node.body, inner)

    visit(tree.body, ())
    return tuple(found)


def symbols_of(text: str, language: str | None) -> tuple[Symbol, ...]:
    if language == "java":
        return java_symbols(text)
    if language == "python":
        return python_symbols(text)
    return ()


__all__ = ["Symbol", "java_symbols", "python_symbols", "symbols_of"]
