"""Language-specific native Code Graph extractors."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.code_intelligence.graph_call_extractors import _extract_python_calls, _extract_regex_calls
from app.services.code_intelligence.graph_primitives import (
    line_number_for_offset,
    script_signature,
    symbol_id,
    symbol_node,
)
from app.services.code_intelligence.graph_route_extractors import (
    _extract_express_routes,
    _extract_fastapi_routes,
    _extract_react_router_routes,
    _extract_spring_routes,
)
from app.services.code_intelligence.outline import _python_ast_outline
from app.services.code_intelligence.outline_java import _tree_sitter_java_outline


@dataclass(frozen=True)
class NativeLanguageExtractor:
    name: str
    languages: tuple[str, ...]
    symbol_extractor: Callable[[str, str, str], list[dict[str, Any]]]
    route_extractor: Callable[[str, str, dict[str, list[dict[str, Any]]]], list[dict[str, Any]]]
    call_extractor: Callable[[str, str, dict[str, dict[str, Any]]], list[dict[str, Any]]]

    def extract_symbols(self, *, relative_path: str, language: str, text: str) -> list[dict[str, Any]]:
        return self.symbol_extractor(relative_path, language, text)

    def extract_routes(
        self, *, relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        return self.route_extractor(relative_path, text, symbol_index)

    def extract_calls(
        self, *, relative_path: str, text: str, symbol_by_id: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.call_extractor(relative_path, text, symbol_by_id)


def extract_symbols(*, relative_path: str, language: str, text: str) -> list[dict[str, Any]]:
    extractor = get_native_language_extractor(language)
    return extractor.extract_symbols(relative_path=relative_path, language=language, text=text) if extractor else []


def extract_routes(
    *,
    relative_path: str,
    language: str,
    text: str,
    symbol_index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    extractor = get_native_language_extractor(language)
    if not extractor:
        return []
    return extractor.extract_routes(relative_path=relative_path, text=text, symbol_index=symbol_index)


def extract_calls(
    *, relative_path: str, language: str, text: str, symbol_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    extractor = get_native_language_extractor(language)
    if not extractor:
        return []
    return extractor.extract_calls(relative_path=relative_path, text=text, symbol_by_id=symbol_by_id)


def _extract_python_symbols(*, relative_path: str, text: str) -> list[dict[str, Any]]:
    outlines = _python_ast_outline(Path(relative_path), text)
    by_parent: dict[tuple[tuple[str, ...], str], str] = {}
    symbols: list[dict[str, Any]] = []
    for item in outlines:
        parents = tuple(str(part) for part in item.get("parents") or [])
        name = str(item.get("name") or "")
        qualified = ".".join([*parents, name]) if parents else name
        node_id = symbol_id(relative_path, qualified, int(item.get("line") or 1))
        by_parent[(parents, name)] = node_id
        parent_id = by_parent.get((parents[:-1], parents[-1])) if parents else ""
        symbols.append(
            symbol_node(
                relative_path=relative_path,
                language="python",
                symbol_id=node_id,
                name=name,
                qualified_name=qualified,
                kind=str(item.get("kind") or "symbol"),
                line=int(item.get("line") or 1),
                end_line=int(item.get("end_line") or item.get("line") or 1),
                signature=str(item.get("signature") or name),
                backend="python_ast",
                parent_id=parent_id or "",
            )
        )
    return symbols


def _extract_script_symbols(*, relative_path: str, language: str, text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    patterns = [
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)")),
        ("function", re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")),
        ("function", re.compile(r"\b(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(")),
        (
            "function",
            re.compile(
                r"\b(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
                r"(?:async\s*)?[A-Za-z_$][A-Za-z0-9_$]*\s*=>"
            ),
        ),
    ]
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            name = match.group(1)
            symbols.append(
                symbol_node(
                    relative_path=relative_path,
                    language=language,
                    symbol_id=symbol_id(relative_path, name, line_no),
                    name=name,
                    qualified_name=name,
                    kind=kind,
                    line=line_no,
                    end_line=line_no,
                    signature=script_signature(line),
                    backend="script_regex",
                )
            )
            break
    return symbols


def _extract_java_symbols(*, relative_path: str, text: str) -> list[dict[str, Any]]:
    outlines = _tree_sitter_java_outline(Path(relative_path), text)
    symbols: list[dict[str, Any]] = []
    package_match = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", text, flags=re.MULTILINE)
    if package_match:
        package_name = package_match.group(1)
        package_line = line_number_for_offset(text, package_match.start())
        symbols.append(
            symbol_node(
                relative_path=relative_path,
                language="java",
                symbol_id=symbol_id(relative_path, package_name, package_line),
                name=package_name,
                qualified_name=package_name,
                kind="package",
                line=package_line,
                end_line=package_line,
                signature=f"package {package_name}",
                backend="java_package_regex",
            )
        )
    for item in outlines:
        parents = [str(part) for part in item.get("parents") or []]
        name = str(item.get("name") or "")
        qualified = ".".join([*parents, name]) if parents else name
        line = int(item.get("line") or 1)
        symbols.append(
            symbol_node(
                relative_path=relative_path,
                language="java",
                symbol_id=symbol_id(relative_path, qualified, line),
                name=name,
                qualified_name=qualified,
                kind=str(item.get("kind") or "symbol"),
                line=line,
                end_line=int(item.get("end_line") or line),
                signature=str(item.get("signature") or name),
                backend=str(item.get("backend") or "java_parser"),
            )
        )
    return symbols


def _python_symbol_adapter(relative_path: str, _language: str, text: str) -> list[dict[str, Any]]:
    return _extract_python_symbols(relative_path=relative_path, text=text)


def _script_symbol_adapter(relative_path: str, language: str, text: str) -> list[dict[str, Any]]:
    return _extract_script_symbols(relative_path=relative_path, language=language, text=text)


def _java_symbol_adapter(relative_path: str, _language: str, text: str) -> list[dict[str, Any]]:
    return _extract_java_symbols(relative_path=relative_path, text=text)


def _python_route_adapter(
    relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return _extract_fastapi_routes(relative_path=relative_path, text=text, symbol_index=symbol_index)


def _script_route_adapter(
    relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return [
        *_extract_express_routes(relative_path=relative_path, text=text, symbol_index=symbol_index),
        *_extract_react_router_routes(relative_path=relative_path, text=text, symbol_index=symbol_index),
    ]


def _java_route_adapter(
    relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return _extract_spring_routes(relative_path=relative_path, text=text, symbol_index=symbol_index)


def _python_call_adapter(
    relative_path: str, text: str, symbol_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return _extract_python_calls(relative_path=relative_path, text=text, symbol_by_id=symbol_by_id)


def _regex_call_adapter(language: str) -> Callable[[str, str, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    def _adapter(relative_path: str, text: str, symbol_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return _extract_regex_calls(
            relative_path=relative_path, text=text, symbol_by_id=symbol_by_id, language=language
        )

    return _adapter


NATIVE_LANGUAGE_EXTRACTORS = (
    NativeLanguageExtractor(
        name="python_ast_fastapi",
        languages=("python",),
        symbol_extractor=_python_symbol_adapter,
        route_extractor=_python_route_adapter,
        call_extractor=_python_call_adapter,
    ),
    NativeLanguageExtractor(
        name="typescript_regex_express",
        languages=("typescript",),
        symbol_extractor=_script_symbol_adapter,
        route_extractor=_script_route_adapter,
        call_extractor=_regex_call_adapter("typescript"),
    ),
    NativeLanguageExtractor(
        name="javascript_regex_express",
        languages=("javascript",),
        symbol_extractor=_script_symbol_adapter,
        route_extractor=_script_route_adapter,
        call_extractor=_regex_call_adapter("javascript"),
    ),
    NativeLanguageExtractor(
        name="java_tree_sitter_spring",
        languages=("java",),
        symbol_extractor=_java_symbol_adapter,
        route_extractor=_java_route_adapter,
        call_extractor=_regex_call_adapter("java"),
    ),
)
NATIVE_LANGUAGE_EXTRACTOR_BY_LANGUAGE = {
    language: extractor for extractor in NATIVE_LANGUAGE_EXTRACTORS for language in extractor.languages
}


def get_native_language_extractor(language: str) -> NativeLanguageExtractor | None:
    return NATIVE_LANGUAGE_EXTRACTOR_BY_LANGUAGE.get(str(language or "").strip())


def list_native_language_extractors() -> list[dict[str, Any]]:
    return [
        {
            "name": extractor.name,
            "languages": list(extractor.languages),
        }
        for extractor in NATIVE_LANGUAGE_EXTRACTORS
    ]


__all__ = [
    "NativeLanguageExtractor",
    "extract_calls",
    "extract_routes",
    "extract_symbols",
    "get_native_language_extractor",
    "list_native_language_extractors",
]
