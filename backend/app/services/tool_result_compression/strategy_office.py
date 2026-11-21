from __future__ import annotations

from typing import Any

from app.services.tool_result_compression.config import build_truncated_excerpt, clamp_config_int
from app.services.tool_result_compression.support import _extract_html_headings, _strip_html


def _compress_office_document_view(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_excerpt_chars = clamp_config_int(
        config,
        "max_excerpt_chars",
        default=1800,
        minimum=300,
        maximum=5000,
    )
    max_issues = clamp_config_int(config, "max_issues", default=40, minimum=5, maximum=200)
    text = str(result.get("text") or result.get("content") or result.get("stdout") or result.get("html") or "").strip()
    issues = result.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    return {
        "file_path": result.get("file_path"),
        "view": result.get("view"),
        "document_type": result.get("document_type"),
        "stats": result.get("stats") if isinstance(result.get("stats"), dict) else {},
        "issue_count": len(issues),
        "issues": issues[:max_issues],
        "excerpt": build_truncated_excerpt(text, max_chars=max_excerpt_chars),
        "text_length": len(text),
        "artifacts": result.get("artifacts") or [],
    }


def _compress_office_element(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_children = clamp_config_int(config, "max_children", default=40, minimum=5, maximum=150)
    max_excerpt_chars = clamp_config_int(
        config,
        "max_excerpt_chars",
        default=1200,
        minimum=200,
        maximum=4000,
    )
    node = result.get("node")
    if not isinstance(node, dict):
        node = result.get("element") if isinstance(result.get("element"), dict) else {}
    children = node.get("children") if isinstance(node.get("children"), list) else []
    text = str(node.get("text") or node.get("content") or result.get("text") or "").strip()
    return {
        "file_path": result.get("file_path"),
        "path": result.get("path") or result.get("element_path"),
        "element_type": node.get("type"),
        "props": node.get("props") if isinstance(node.get("props"), dict) else {},
        "excerpt": build_truncated_excerpt(text, max_chars=max_excerpt_chars),
        "text_length": len(text),
        "children": children[:max_children],
        "child_count": len(children),
        "omitted_child_count": max(0, len(children) - len(children[:max_children])),
    }


def _compress_office_query(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_matches = clamp_config_int(config, "max_matches", default=80, minimum=5, maximum=250)
    matches = result.get("matches") or result.get("results") or []
    if not isinstance(matches, list):
        matches = []
    summarized: list[dict[str, Any]] = []
    for item in matches[:max_matches]:
        if not isinstance(item, dict):
            continue
        summarized.append(
            {
                "path": item.get("path"),
                "type": item.get("type"),
                "text": str(item.get("text") or item.get("content") or "")[:220],
                "props": item.get("props") if isinstance(item.get("props"), dict) else {},
            }
        )
    return {
        "file_path": result.get("file_path"),
        "selector": result.get("selector"),
        "match_count": len(matches),
        "matches": summarized,
        "omitted_count": max(0, len(matches) - len(summarized)),
    }


def _compress_office_html(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_headings = clamp_config_int(config, "max_headings", default=12, minimum=1, maximum=30)
    max_excerpt_chars = clamp_config_int(
        config,
        "max_excerpt_chars",
        default=1400,
        minimum=300,
        maximum=5000,
    )
    html = str(result.get("html") or result.get("content") or result.get("stdout") or "")
    text = _strip_html(html)
    return {
        "file_path": result.get("file_path"),
        "document_type": result.get("document_type"),
        "headings": _extract_html_headings(html, max_headings=max_headings),
        "excerpt": build_truncated_excerpt(text, max_chars=max_excerpt_chars),
        "text_length": len(text),
        "artifacts": result.get("artifacts") or [],
    }
