"""The code elements of a checkout that a framework change can hit.

Deterministic and bounded; it reads files and never runs a build or a subprocess. It collects:

- ``import``: Java and Kotlin import statements, with their fully qualified names;
- ``annotation``: annotations in use (``@JsonComponent``);
- ``property``: configuration keys from ``application*.properties``, ``application*.yml`` and
  ``application*.yaml``, with YAML nesting flattened to dotted keys;
- ``dependency``: Maven ``<artifactId>`` entries (dependencies, parent, plugins), Gradle
  ``group:artifact`` coordinates, and Gradle plugin ids;
- ``build_property``: Maven ``<properties>`` names (``java.version``) with their values.

Every element carries its path relative to the scanned root and its 1-based line, so an impact
item points at the exact place a change applies to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILES = 5000
MAX_FILE_BYTES = 1_000_000
MAX_ELEMENTS = 50_000
_SKIP_DIRS = frozenset({".git", "target", "build", "node_modules", ".gradle", ".idea", "out", "dist", ".mvn"})

KIND_IMPORT = "import"
KIND_ANNOTATION = "annotation"
KIND_PROPERTY = "property"
KIND_DEPENDENCY = "dependency"
KIND_BUILD_PROPERTY = "build_property"

_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*(?:\.\*)?)\s*;?\s*$")
_ANNOTATION = re.compile(r"(?<![\w.@])@([A-Z][A-Za-z0-9_]*)\b")
_PROPERTY_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*[=:]")
_YAML_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.\-]+)\s*:(.*)$")
_MAVEN_ARTIFACT = re.compile(r"<artifactId>\s*([\w.\-]+)\s*</artifactId>")
_MAVEN_PROPERTY = re.compile(r"^\s*<([\w.\-]+)>\s*([^<]{1,120})\s*</\1>\s*$")
_GRADLE_COORDINATE = re.compile(r"""["']([\w.\-]+):([\w.\-]+)(?::([\w.\-]+))?["']""")
_GRADLE_PLUGIN = re.compile(r"""\bid\s*\(?\s*["']([\w.\-]+)["']""")


@dataclass(frozen=True, slots=True)
class CodeElement:
    kind: str
    value: str
    path: str
    line: int
    detail: str = ""


def _files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= MAX_FILES:
            break
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE_BYTES:
            files.append(path)
    return files


def _yaml_keys(lines: list[str]) -> list[tuple[int, str]]:
    stack: list[tuple[int, str]] = []
    keys: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith(("#", "-")):
            continue
        match = _YAML_KEY.match(line)
        if match is None:
            continue
        indent = len(match.group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, match.group(2)))
        if match.group(3).strip():
            keys.append((number, ".".join(key for _, key in stack)))
    return keys


def _elements_of(path: Path, relative: str) -> list[CodeElement]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return elements_of_text(relative, text)


def is_scanned_file(relative: str) -> bool:
    """Whether the scanner reads elements from a file of this name (by its closed file classes)."""
    name = relative.rsplit("/", 1)[-1]
    return (
        name.endswith((".java", ".kt", ".kts", ".groovy", ".gradle"))
        or name == "pom.xml"
        or name == "libs.versions.toml"
        or (name.startswith("application") and name.endswith((".properties", ".yml", ".yaml")))
    )


def elements_of_text(relative: str, text: str) -> list[CodeElement]:
    """The code elements of one file's text; ``relative`` is its repository-relative path.

    The file class comes from the file name only, exactly as for a checkout scan, so an uploaded
    file and the same file in a checkout yield the same elements.
    """
    lines = text.splitlines()
    name = relative.rsplit("/", 1)[-1]
    found: list[CodeElement] = []
    if name.endswith((".java", ".kt", ".kts", ".groovy")) and not name.endswith(".gradle.kts"):
        for number, line in enumerate(lines, start=1):
            if (match := _IMPORT.match(line)) is not None:
                found.append(CodeElement(KIND_IMPORT, match.group(1), relative, number))
            elif "@" in line:
                found += [
                    CodeElement(KIND_ANNOTATION, m.group(1), relative, number) for m in _ANNOTATION.finditer(line)
                ]
    elif name.startswith("application") and name.endswith(".properties"):
        for number, line in enumerate(lines, start=1):
            if not line.lstrip().startswith(("#", "!")) and (match := _PROPERTY_LINE.match(line)) is not None:
                found.append(CodeElement(KIND_PROPERTY, match.group(1), relative, number))
    elif name.startswith("application") and name.endswith((".yml", ".yaml")):
        found += [CodeElement(KIND_PROPERTY, key, relative, number) for number, key in _yaml_keys(lines)]
    elif name == "pom.xml":
        in_properties = False
        for number, line in enumerate(lines, start=1):
            if "<properties>" in line:
                in_properties = True
            elif "</properties>" in line:
                in_properties = False
            elif in_properties and (match := _MAVEN_PROPERTY.match(line)) is not None:
                value = match.group(2).strip()
                found.append(CodeElement(KIND_BUILD_PROPERTY, match.group(1), relative, number, value))
            found += [
                CodeElement(KIND_DEPENDENCY, m.group(1), relative, number) for m in _MAVEN_ARTIFACT.finditer(line)
            ]
    elif name.endswith((".gradle", ".gradle.kts")) or name == "libs.versions.toml":
        for number, line in enumerate(lines, start=1):
            for match in _GRADLE_COORDINATE.finditer(line):
                detail = f"{match.group(1)}:{match.group(2)}" + (f":{match.group(3)}" if match.group(3) else "")
                found.append(CodeElement(KIND_DEPENDENCY, match.group(2), relative, number, detail))
            found += [CodeElement(KIND_DEPENDENCY, m.group(1), relative, number) for m in _GRADLE_PLUGIN.finditer(line)]
    return found


def scan_checkout(root: Path) -> tuple[CodeElement, ...]:
    """Every code element under ``root``, bounded; ``root`` must be a directory."""
    root = root.resolve()
    elements: list[CodeElement] = []
    for path in _files(root):
        elements.extend(_elements_of(path, path.relative_to(root).as_posix()))
        if len(elements) >= MAX_ELEMENTS:
            break
    return tuple(elements[:MAX_ELEMENTS])


__all__ = [
    "KIND_ANNOTATION",
    "KIND_BUILD_PROPERTY",
    "KIND_DEPENDENCY",
    "KIND_IMPORT",
    "KIND_PROPERTY",
    "CodeElement",
    "elements_of_text",
    "is_scanned_file",
    "scan_checkout",
]
