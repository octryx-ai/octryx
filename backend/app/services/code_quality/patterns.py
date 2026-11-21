from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.services.code_quality.repo_files import NODE_MODULE_DIRS


def _candidate_files(repo_root: Path, max_files: int) -> list[Path]:
    candidate_files: list[Path] = []
    for suffix in (".py", ".ts", ".tsx", ".js", ".go", ".java", ".kt"):
        candidate_files.extend(
            path
            for path in repo_root.rglob(f"*{suffix}")
            if path.is_file() and not any(part in NODE_MODULE_DIRS for part in path.parts)
        )
    return sorted(candidate_files)[:max_files]


def _count_patterns(candidate_files: list[Path]) -> dict[str, int]:
    counts = dict.fromkeys(
        ("snake_case", "camel_case", "relative_imports", "absolute_imports", "raise_http_exception",
         "json_response", "logger", "test_files"),
        0,
    )
    for path in candidate_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.name.startswith("test_") or "/tests/" in str(path):
            counts["test_files"] += 1
        counts["snake_case"] += len(re.findall(r"\bdef\s+[a-z0-9_]+\(", text))
        counts["camel_case"] += len(re.findall(r"\bfunction\s+[a-z][A-Za-z0-9]*\(", text))
        counts["relative_imports"] += len(re.findall(r"^\s*from\s+\.", text, re.MULTILINE))
        counts["absolute_imports"] += len(re.findall(r"^\s*(?:from|import)\s+[a-zA-Z0-9_]+", text, re.MULTILINE))
        counts["raise_http_exception"] += text.count("raise HTTPException")
        counts["json_response"] += text.count("JSONResponse(")
        counts["logger"] += text.count("logger.")
    return counts


def analyze_codebase_patterns_impl(
    *,
    cwd: Path,
    max_files: int = 20,
    load_config_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    config = load_config_fn(cwd)
    repo_root = Path(str(config.get("repo_root") or cwd)).resolve()
    candidate_files = _candidate_files(repo_root, max_files)
    counts = _count_patterns(candidate_files)
    test_files = counts["test_files"]

    naming = "snake_case" if counts["snake_case"] >= counts["camel_case"] else "mixed_or_camel"
    if counts["relative_imports"] and counts["absolute_imports"]:
        import_style = "mixed"
    elif counts["relative_imports"]:
        import_style = "relative-heavy"
    else:
        import_style = "mostly-absolute"

    return {
        "repo_root": str(repo_root),
        "config": config,
        "representative_files": [str(path.relative_to(repo_root)) for path in candidate_files],
        "naming_convention": naming,
        "import_style": import_style,
        "error_handling_patterns": {
            "raise_http_exception": counts["raise_http_exception"],
            "json_response": counts["json_response"],
            "logger_usage": counts["logger"],
        },
        "test_patterns": {
            "sampled_test_files": test_files,
            "test_file_naming": "test_*" if test_files else "unknown",
        },
    }
