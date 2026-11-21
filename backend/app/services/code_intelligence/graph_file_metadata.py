"""File-level metadata helpers for native Code Graph extraction."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Any

GENERATED_PATH_MARKERS = {
    ".generated.",
    "/generated/",
    "/gen/",
    "/dist/",
    "/build/",
    "/target/generated-sources/",
}
GENERATED_NAME_SUFFIXES = {
    ".g.py",
    ".g.ts",
    ".g.tsx",
    ".g.js",
    ".g.jsx",
    ".pb.go",
}
TEST_PATH_MARKERS = {
    "/__tests__/",
    "/spec/",
    "/test/",
    "/tests/",
}
VENDOR_PATH_MARKERS = {
    "/.pnpm/",
    "/node_modules/",
    "/third_party/",
    "/vendor/",
}


def build_file_extraction_metadata(*, relative_path: str, language: str, text: str) -> dict[str, Any]:
    """Return deterministic file flags and parser status for graph ingestion."""

    parse_error = detect_parse_error(relative_path=relative_path, language=language, text=text)
    classification = classify_code_graph_file(relative_path)
    return {
        **classification,
        "parse_status": "error" if parse_error else "ready",
        "parse_error": parse_error or None,
    }


def classify_code_graph_file(relative_path: str) -> dict[str, Any]:
    normalized = f"/{PurePosixPath(relative_path).as_posix().lower().lstrip('/')}"
    name = PurePosixPath(normalized).name
    is_generated = (
        any(marker in normalized for marker in GENERATED_PATH_MARKERS)
        or any(name.endswith(suffix) for suffix in GENERATED_NAME_SUFFIXES)
        or name.endswith(".generated.ts")
        or name.endswith(".generated.js")
    )
    is_test = (
        any(marker in normalized for marker in TEST_PATH_MARKERS)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
    )
    is_vendor = any(marker in normalized for marker in VENDOR_PATH_MARKERS)
    return {
        "is_generated": is_generated,
        "is_test": is_test,
        "is_vendor": is_vendor,
        "index_priority": "low" if is_generated or is_vendor else "normal",
    }


def detect_parse_error(*, relative_path: str, language: str, text: str) -> str:
    if language != "python" or not text:
        return ""
    try:
        ast.parse(text, filename=relative_path)
    except SyntaxError as exc:
        return f"{exc.__class__.__name__}: {exc.msg} at line {exc.lineno or 0}"
    return ""


__all__ = ["build_file_extraction_metadata", "classify_code_graph_file", "detect_parse_error"]
