"""Import parsing and module resolution for native Code Graph extraction."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any


def extract_import_targets(text: str, *, language: str) -> list[str]:
    if language == "python":
        targets = re.findall(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\b", text, flags=re.MULTILINE)
        targets.extend(re.findall(r"^\s*import\s+([A-Za-z0-9_\.]+)", text, flags=re.MULTILINE))
        return targets
    if language in {"typescript", "javascript"}:
        return [
            *re.findall(r"from\s+['\"]([^'\"]+)['\"]", text),
            *re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", text),
        ]
    if language == "java":
        return re.findall(r"^\s*import\s+([A-Za-z0-9_\.]+);", text, flags=re.MULTILINE)
    return []


def resolve_import_target(target: str, *, language: str, module_index: dict[str, str], source_path: str = "") -> str:
    normalized = target.strip().lstrip(".")
    candidates = {normalized, normalized.replace(".", "/")}
    if language in {"typescript", "javascript"}:
        if target.strip().startswith(".") and source_path:
            relative_target = PurePosixPath(source_path).parent / target.strip()
            normalized_relative = str(relative_target)
            while normalized_relative.startswith("./"):
                normalized_relative = normalized_relative[2:]
            candidates.update({normalized_relative, normalized_relative.replace("//", "/")})
        candidates.update({f"{normalized}.ts", f"{normalized}.tsx", f"{normalized}.js", f"{normalized}.jsx"})
        candidates.update({f"{normalized}/index.ts", f"{normalized}/index.js"})
        candidates.update({f"{candidate}.ts" for candidate in tuple(candidates) if not PurePosixPath(candidate).suffix})
        candidates.update({f"{candidate}.tsx" for candidate in tuple(candidates) if not PurePosixPath(candidate).suffix})
        candidates.update({f"{candidate}.js" for candidate in tuple(candidates) if not PurePosixPath(candidate).suffix})
        candidates.update({f"{candidate}.jsx" for candidate in tuple(candidates) if not PurePosixPath(candidate).suffix})
    for candidate in candidates:
        if candidate in module_index:
            return module_index[candidate]
    return ""


def build_module_index(file_items: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in file_items:
        path = str(item.get("path") or "")
        language = str(item.get("language") or "")
        file_path = Path(path)
        without_suffix = str(file_path.with_suffix(""))
        candidates = {path, without_suffix, file_path.stem, without_suffix.replace("/", ".")}
        if language == "python" and file_path.name == "__init__.py":
            candidates.add(str(file_path.parent).replace("/", "."))
        for candidate in candidates:
            if candidate:
                index.setdefault(candidate, path)
    return index


def language_for_file_item(file_items: list[dict[str, Any]], relative_path: str) -> str:
    for item in file_items:
        if str(item.get("path") or "") == relative_path:
            return str(item.get("language") or "unknown")
    return "unknown"


__all__ = ["build_module_index", "extract_import_targets", "language_for_file_item", "resolve_import_target"]
