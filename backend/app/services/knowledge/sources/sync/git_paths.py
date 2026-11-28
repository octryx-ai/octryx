"""Paths of a repository snapshot: include/exclude globs, the path rule, and the language facet. Globs know only ``*``,
``?`` and ``**``, anchored at the root."""

from __future__ import annotations

import re

from ...ledger.errors import InvalidEvidenceRequestError

MAX_GLOBS = 20
MAX_GLOB_CHARS = 200
MAX_PATH_CHARS = 400
_GLOB = re.compile(r"^[A-Za-z0-9._/*?@+~ -]{1,200}$")

_LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".scala": "scala",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".sh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".xml": "xml",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".properties": "properties",
    ".md": "markdown",
    ".adoc": "asciidoc",
}
_LANGUAGE_BY_NAME = {"Dockerfile": "dockerfile", "Makefile": "makefile", "pom.xml": "xml"}


class PathFilter:
    __slots__ = ("exclude", "include", "_exclude", "_include")

    def __init__(self, include: tuple[str, ...], exclude: tuple[str, ...]) -> None:
        self.include, self.exclude = include, exclude
        self._include = tuple(_compile(glob) for glob in include)
        self._exclude = tuple(_compile(glob) for glob in exclude)

    def admits(self, path: str) -> bool:
        included = not self._include or any(pattern.fullmatch(path) for pattern in self._include)
        return included and not any(pattern.fullmatch(path) for pattern in self._exclude)


def _compile(glob: str) -> re.Pattern[str]:
    out: list[str] = []
    index = 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:[^/]+/)*")
            index += 3
        elif glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out))


def validate_globs(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple) or len(raw) > MAX_GLOBS:
        raise InvalidEvidenceRequestError()
    globs: list[str] = []
    for item in raw:
        if type(item) is not str:
            raise InvalidEvidenceRequestError()
        glob = item.strip()
        if not _GLOB.fullmatch(glob) or glob.startswith("/") or "***" in glob:
            raise InvalidEvidenceRequestError()
        if any(segment in (".", "..") for segment in glob.split("/")):
            raise InvalidEvidenceRequestError()
        globs.append(glob)
    return tuple(dict.fromkeys(globs))


def supported_path(path: str) -> bool:
    if not path or len(path) > MAX_PATH_CHARS or path.startswith("/") or path.endswith("/"):
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def language_of(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name in _LANGUAGE_BY_NAME:
        return _LANGUAGE_BY_NAME[name]
    dot = name.rfind(".")
    return _LANGUAGE_BY_SUFFIX.get(name[dot:].lower()) if dot > 0 else None


__all__ = ["MAX_GLOBS", "MAX_PATH_CHARS", "PathFilter", "language_of", "supported_path", "validate_globs"]
