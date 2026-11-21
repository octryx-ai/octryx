"""Java outline extraction: tree-sitter when installed, line-based regex fallback otherwise."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_runtime import _truncate

try:
    from tree_sitter import Language as TreeSitterLanguage
    from tree_sitter import Parser as TreeSitterParser
except Exception:  # pragma: no cover - optional dependency
    TreeSitterLanguage = None
    TreeSitterParser = None

try:
    import tree_sitter_java
except Exception:  # pragma: no cover - optional dependency
    tree_sitter_java = None

_TYPE_DECLARATION_PATTERN = (
    r"^(?:(?:public|protected|private)\s+)?(?:abstract\s+)?(?:class|interface|enum|record)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)
_METHOD_PATTERN = (
    r"^\s*(?:public|private|protected|static|final|synchronized|abstract)?\s*[A-Za-z_<>\[\],? ]+\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*[(]"
)
_FIELD_PATTERN = (
    r"^(?:public|private|protected|static|final|volatile|transient)?(?:\s+[A-Za-z_<>\[\],? ]+)+\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*[;,=]"
)
_TYPE_KINDS = {"class": "class", "interface": "interface", "enum": "enum", "record": "record"}
_DECLARATION_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
}


def _tree_sitter_java_outline(file_path: Path, text: str) -> list[dict[str, Any]]:
    if TreeSitterParser is None or TreeSitterLanguage is None or tree_sitter_java is None:
        return _java_regex_outline(source=text)

    source_bytes = text.encode("utf-8")
    try:
        parser = TreeSitterParser(TreeSitterLanguage(tree_sitter_java.language()))
        tree = parser.parse(source_bytes)
    except Exception:
        return _java_regex_outline(source=text)

    nodes: list[dict[str, Any]] = []
    _visit_java_node(tree.root_node, [], source_bytes=source_bytes, nodes=nodes)
    if nodes:
        return sorted(nodes, key=lambda item: (int(item.get("line") or 1), str(item.get("name") or "")))
    return _java_regex_outline(
        source=text, fallback_class_names=[item["name"] for item in nodes if item["kind"] == "class"]
    )


def _java_regex_outline(*, source: str, fallback_class_names: list[str] | None = None) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    class_names = list(fallback_class_names or [])
    for index, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if match := re.match(_TYPE_DECLARATION_PATTERN, line):
            name = match.group(1)
            class_names.append(name)
            kind = _TYPE_KINDS.get(match.group(0).split()[1], "class")
            nodes.append(_regex_node(name=name, kind=kind, line=index, signature=line.rstrip("{").strip()))
            continue
        if re.match(_METHOD_PATTERN, line):
            name = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*[/(]", line)[0]
            if name in {"if", "for", "while", "catch", "switch", "new"}:
                continue
            kind = "constructor" if name in class_names else "method"
            nodes.append(_regex_node(name=name, kind=kind, line=index, signature=line.split("{", 1)[0].strip()))
            continue
        if re.match(_FIELD_PATTERN, line):
            nodes.extend(_regex_field_nodes(line, index))
    return nodes


def _regex_field_nodes(line: str, index: int) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for field_name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*[;,=]", line):
        if field_name in {"if", "for", "while", "new", "return"}:
            continue
        nodes.append(_regex_node(name=field_name, kind="field", line=index, signature=line.rstrip(";").strip()))
    return nodes


def _regex_node(*, name: str, kind: str, line: int, signature: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "line": line,
        "end_line": line,
        "language": "java",
        "signature": _truncate(signature, max_chars=220),
        "parents": [],
        "backend": "tree-sitter",
    }


def _node_text(node: Any, source_bytes: bytes) -> str:
    # tree-sitter offsets are BYTE offsets into the encoded source; slicing
    # the str with them corrupts names as soon as any earlier character is
    # multi-byte (umlauts, copyright signs in license headers, ...).
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _visit_java_node(node: Any, parents: list[str], *, source_bytes: bytes, nodes: list[dict[str, Any]]) -> None:
    node_type = str(node.type)
    if node_type in _DECLARATION_KINDS:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = _node_text(name_node, source_bytes).strip()
            signature = _node_text(node, source_bytes).split("{", 1)[0].strip().replace("\n", " ")
            kind = _DECLARATION_KINDS[node_type]
            nodes.append(_tree_node(node, name=name, kind=kind, signature=signature, parents=parents))
            parents = [*parents, name]
    elif node_type == "field_declaration":
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            name = _node_text(name_node, source_bytes).strip()
            signature = _node_text(node, source_bytes).strip().replace("\n", " ")
            nodes.append(_tree_node(child, name=name, kind="field", signature=signature, parents=parents))
    for child in node.children:
        _visit_java_node(child, parents, source_bytes=source_bytes, nodes=nodes)


def _tree_node(span: Any, *, name: str, kind: str, signature: str, parents: list[str]) -> dict[str, Any]:
    start = int(span.start_point[0]) + 1
    end = int(span.end_point[0]) + 1
    truncated = _truncate(signature, max_chars=220)
    return {
        "name": name,
        "kind": kind,
        "line": start,
        "end_line": max(start, end),
        "language": "java",
        "signature": truncated or name,
        "parents": list(parents),
        "backend": "tree-sitter",
    }
