"""Binary and capability detection helpers for code intelligence storage."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any


def _find_binary(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    fallback_roots = [
        Path.home() / "go" / "bin",
        Path.home() / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]
    for root in fallback_roots:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def _binary_available(name: str) -> bool:
    return _find_binary(name) is not None


def detect_code_intelligence_capabilities() -> dict[str, Any]:
    tree_sitter_python = importlib.util.find_spec("tree_sitter") is not None
    tree_sitter_cli = _binary_available("tree-sitter")
    zoekt_index = _binary_available("zoekt-index")
    zoekt_git_index = _binary_available("zoekt-git-index")
    zoekt_search = _binary_available("zoekt")
    zoekt_web = _binary_available("zoekt-webserver")
    zoekt_index_available = bool(zoekt_index or zoekt_git_index)
    return {
        "search": {
            "zoekt": {
                "available": zoekt_index_available,
                "index_available": zoekt_index_available,
                "search_available": zoekt_search,
                "web_available": zoekt_web,
                "binaries": {
                    "zoekt-index": zoekt_index,
                    "zoekt-git-index": zoekt_git_index,
                    "zoekt": zoekt_search,
                    "zoekt-webserver": zoekt_web,
                },
            },
            "ripgrep": {"available": _binary_available("rg")},
        },
        "semantic": {
            "lsp": {"available": True},
        },
        "structure": {
            "tree_sitter": {
                "available": bool(tree_sitter_python or tree_sitter_cli),
                "python_library": tree_sitter_python,
                "cli": tree_sitter_cli,
            },
            "regex": {"available": True},
        },
        "graph": {
            "code_graph": {
                "available": True,
                "backend": "native",
                "storage": "database_or_file",
            },
        },
    }
