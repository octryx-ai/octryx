"""Constants shared by code intelligence storage helpers."""

from __future__ import annotations

import re
from pathlib import Path

from ...config import get_settings

_SETTINGS = get_settings()
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CODE_INTELLIGENCE_DIR = Path(_SETTINGS.artifact_store_dir).resolve().parent / "code-intelligence"
_IGNORE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
_SOURCE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
}
_LANGUAGE_TO_LSP_LANGUAGE: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "go": "go",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "rust": "rust",
}
_LANGUAGE_SCIP_BINARIES: dict[str, tuple[str, ...]] = {
    "go": ("scip-go",),
    "java": ("scip-java",),
    "python": ("scip-python",),
    "typescript": ("scip-typescript",),
    "javascript": ("scip-typescript",),
    "c": ("scip-clang",),
    "cpp": ("scip-clang",),
}
_SCIP_BUILDABLE_LANGUAGES = {"go", "python", "typescript", "javascript", "c", "cpp"}
_SCIP_SNAPSHOT_METADATA_PATTERN = re.compile(
    r"^\s*//\s+(?P<key>display_name|signature_documentation|kind)\s+(?P<value>.+?)\s*$"
)
_SCIP_SNAPSHOT_OCCURRENCE_PATTERN = re.compile(
    r"^\s*//\s*(?P<carets>\^+)\s+(?P<kind>definition|reference)\s+.+\s+(?P<symbol>\S+)\s*$"
)
_SYMBOL_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "python": [
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)),
        ("function", re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ],
    "typescript": [
        (
            "class",
            re.compile(
                r"^\s*export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b|^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                re.MULTILINE,
            ),
        ),
        (
            "interface",
            re.compile(
                r"^\s*export\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)\b|^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                re.MULTILINE,
            ),
        ),
        (
            "function",
            re.compile(
                r"^\s*export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(|^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                re.MULTILINE,
            ),
        ),
        ("function", re.compile(r"^\s*(?:const|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)),
    ],
    "javascript": [
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)),
        ("function", re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
        ("function", re.compile(r"^\s*(?:const|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)),
    ],
    "go": [
        ("type", re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)),
        ("function", re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)),
    ],
    "java": [
        ("class", re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("interface", re.compile(r"\binterface\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("enum", re.compile(r"\benum\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        (
            "method",
            re.compile(
                r"^\s*(?:public|protected|private|static|final|synchronized|abstract|\s)+[\w<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                re.MULTILINE,
            ),
        ),
    ],
    "c": [
        ("struct", re.compile(r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        (
            "function",
            re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_\s\*]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*\{", re.MULTILINE),
        ),
    ],
    "cpp": [
        ("class", re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("struct", re.compile(r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        (
            "function",
            re.compile(
                r"^\s*[A-Za-z_:~][A-Za-z0-9_:<>\s\*&]*\s+([A-Za-z_~][A-Za-z0-9_:~]*)\s*\([^;]*\)\s*(?:const)?\s*\{",
                re.MULTILINE,
            ),
        ),
    ],
}
