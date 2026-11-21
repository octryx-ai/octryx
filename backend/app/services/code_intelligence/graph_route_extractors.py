"""Route extractors (FastAPI, Express, React Router, Spring) for the native Code Graph."""

from __future__ import annotations

import re
from typing import Any

from app.services.code_intelligence.graph_primitives import (
    CALL_KEYWORDS,
    line_number_for_offset,
    route_edge,
    route_node,
    single_symbol,
)


def _extract_fastapi_routes(
    *, relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    pending: tuple[str, str, int] | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if match := re.search(r"@\w+\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", line):
            pending = (match.group(1).upper(), match.group(2), line_no)
            continue
        if pending and (match := re.search(r"\b(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)):
            handler = match.group(1)
            node = route_node(relative_path, "fastapi", pending[0], pending[1], pending[2])
            target = single_symbol(symbol_index, handler)
            if target:
                routes.append({"node": node, "edge": route_edge(node["id"], target["id"], handler)})
            pending = None
    return routes


def _extract_express_routes(
    *, relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    route_pattern = re.compile(
        r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
        r"([A-Za-z_$][A-Za-z0-9_$]*)"
    )
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = route_pattern.search(line)
        if not match:
            continue
        node = route_node(relative_path, "express", match.group(1).upper(), match.group(2), line_no)
        target = single_symbol(symbol_index, match.group(3))
        if target:
            routes.append({"node": node, "edge": route_edge(node["id"], target["id"], match.group(3))})
    return routes


def _extract_react_router_routes(
    *, relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    patterns = [
        re.compile(
            r"<Route\b[^>]*\bpath\s*=\s*['\"]([^'\"]+)['\"][^>]*\belement\s*=\s*\{\s*<([A-Za-z_$][A-Za-z0-9_$]*)\b",
            flags=re.DOTALL,
        ),
        re.compile(
            r"\bpath\s*:\s*['\"]([^'\"]+)['\"][^{}]*(?:element\s*:\s*<|Component\s*:\s*)([A-Za-z_$][A-Za-z0-9_$]*)",
            flags=re.DOTALL,
        ),
    ]
    seen: set[tuple[str, str, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            route_path = match.group(1)
            component = match.group(2)
            line_no = line_number_for_offset(text, match.start())
            key = (route_path, component, line_no)
            if key in seen:
                continue
            seen.add(key)
            node = route_node(relative_path, "react_router", "UI", route_path, line_no)
            target = single_symbol(symbol_index, component)
            if target:
                routes.append({"node": node, "edge": route_edge(node["id"], target["id"], component)})
    return routes


def _extract_spring_routes(
    *, relative_path: str, text: str, symbol_index: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    pending: tuple[str, str, int] | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = re.search(r"@(Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)['\"]", line)
        if match:
            pending = (match.group(1).removesuffix("Mapping").upper(), match.group(2), line_no)
            continue
        match = re.search(r"@RequestMapping\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)['\"]", line)
        if match:
            pending = ("ANY", match.group(1), line_no)
            continue
        if pending and (method := re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)):
            handler = method.group(1)
            if handler in CALL_KEYWORDS:
                continue
            node = route_node(relative_path, "spring", pending[0], pending[1], pending[2])
            target = single_symbol(symbol_index, handler)
            if target:
                routes.append({"node": node, "edge": route_edge(node["id"], target["id"], handler)})
            pending = None
    return routes
