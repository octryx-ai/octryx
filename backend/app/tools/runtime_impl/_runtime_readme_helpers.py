"""Module discovery helpers for README generation: build file metadata, key files and module descriptors."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

MAVEN_BUILD_FILE_NAME = "pom.xml"
NODE_PACKAGE_FILE_NAME = "package.json"
README_SOURCE_FILE_SUFFIXES = frozenset({".java", ".kt"})
README_KEY_FILE_SUFFIXES = frozenset({".java", ".kt", ".xml", ".properties", ".yml", ".yaml", ".json"})
README_CONFIG_FILE_PATTERNS = (
    "application*.yml",
    "application*.yaml",
    "application*.properties",
    "*.xml",
    "*.json",
)
README_TEST_FILE_PATTERNS = ("*Test.java", "*IT.java", "*Spec.java")


def _extract_xml_text(root: ElementTree.Element, tag_name: str) -> str:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == tag_name and element.text:
            return element.text.strip()
    return ""


def _parse_build_file_metadata(path: Path) -> dict[str, Any]:
    if path.name == MAVEN_BUILD_FILE_NAME:
        try:
            root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
            return {
                "kind": "maven",
                "artifact_id": _extract_xml_text(root, "artifactId"),
                "group_id": _extract_xml_text(root, "groupId"),
                "packaging": _extract_xml_text(root, "packaging") or "jar",
            }
        except Exception:
            text = path.read_text(encoding="utf-8", errors="replace")
            return {
                "kind": "maven",
                "artifact_id": re.search(r"<artifactId>([^<]+)</artifactId>", text).group(1)
                if re.search(r"<artifactId>([^<]+)</artifactId>", text)
                else "",
            }
    if path.name == NODE_PACKAGE_FILE_NAME:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return {
                "kind": "node",
                "package_name": payload.get("name") or "",
                "version": payload.get("version") or "",
            }
        except Exception:
            return {"kind": "node"}
    return {"kind": path.name}


def _read_text_if_exists(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _module_summarizer(modules: list[dict[str, Any]], missing_after_write: list[str]) -> dict[str, Any]:
    """Summarize generated vs. missing module readmes for caller-facing reporting."""

    return {
        "module_count": len(modules),
        "missing_count": len(missing_after_write),
        "missing": list(missing_after_write),
    }


def _module_kind_from_path(relative_path: str) -> str:
    if relative_path.startswith("javaagent/"):
        return "javaagent"
    if relative_path.startswith("extensions/"):
        return "extension"
    if relative_path.startswith("application-center/"):
        return "application-center"
    if relative_path.startswith("tooling/"):
        return "tooling"
    return "module"




def _first_matching_files(module_dir: Path, patterns: tuple[str, ...], limit: int = 8) -> list[str]:
    collected: list[str] = []
    for pattern in patterns:
        for candidate in sorted(module_dir.rglob(pattern)):
            if not candidate.is_file():
                continue
            if any(part in {".git", "target", "node_modules", "dist", "build"} for part in candidate.parts):
                continue
            relative = str(candidate.relative_to(module_dir))
            if relative not in collected:
                collected.append(relative)
            if len(collected) >= limit:
                return collected
    return collected


def _extract_package_name(java_file: Path) -> str:
    text = _read_text_if_exists(java_file)
    match = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", text, re.MULTILINE)
    return match.group(1) if match else ""


def _collect_notable_sources(module_dir: Path, limit: int = 6) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for source_root in ("src/main/java", "src/main/kotlin"):
        root = module_dir / source_root
        if not root.exists():
            continue
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in README_SOURCE_FILE_SUFFIXES:
                continue
            lowered_name = file_path.name.lower()
            if not any(
                token in lowered_name
                for token in (
                    "agent",
                    "plugin",
                    "service",
                    "controller",
                    "application",
                    "config",
                    "factory",
                    "listener",
                )
            ):
                continue
            candidates.append(
                {
                    "path": str(file_path.relative_to(module_dir)),
                    "package": _extract_package_name(file_path),
                    "name": file_path.stem,
                }
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def _summarize_top_level_directory(directory: Path, limit: int = 10) -> list[str]:
    summary: list[str] = []
    if not directory.exists():
        return summary
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.startswith(".") or child.name in {"target", "build", "dist", "node_modules"}:
            continue
        suffix = "/" if child.is_dir() else ""
        summary.append(f"{child.name}{suffix}")
        if len(summary) >= limit:
            break
    return summary


def _collect_key_files(module_dir: Path, limit: int = 6) -> list[str]:
    candidates: list[str] = []
    for relative_root in (
        "src/main/java",
        "src/main/kotlin",
        "src/main/resources",
        "src/test/java",
        "src/test/resources",
    ):
        root = module_dir / relative_root
        if not root.exists():
            continue
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in README_KEY_FILE_SUFFIXES:
                continue
            candidates.append(str(file_path.relative_to(module_dir)))
            if len(candidates) >= limit:
                return candidates
    return candidates


def _build_module_descriptor(module_dir: Path, repo_path: Path) -> dict[str, Any]:
    pom_path = module_dir / MAVEN_BUILD_FILE_NAME
    package_path = module_dir / NODE_PACKAGE_FILE_NAME
    build_file = pom_path if pom_path.exists() else package_path if package_path.exists() else None
    metadata = _parse_build_file_metadata(build_file) if build_file else {"kind": "unknown"}
    relative_to_repo = str(module_dir.relative_to(repo_path))
    module_kind = _module_kind_from_path(relative_to_repo)
    return {
        "name": module_dir.name,
        "path": relative_to_repo,
        "kind": module_kind,
        "artifact_id": metadata.get("artifact_id") or metadata.get("package_name") or module_dir.name,
        "group_id": metadata.get("group_id") or "",
        "packaging": metadata.get("packaging") or metadata.get("kind") or "",
        "key_files": _collect_key_files(module_dir),
        "config_files": _first_matching_files(module_dir, README_CONFIG_FILE_PATTERNS, limit=8),
        "test_files": _first_matching_files(module_dir, README_TEST_FILE_PATTERNS, limit=6),
        "notable_sources": _collect_notable_sources(module_dir),
        "top_level_entries": _summarize_top_level_directory(module_dir),
        "has_tests": (module_dir / "src/test").exists(),
        "has_main_sources": (module_dir / "src/main").exists(),
        "build_file_name": build_file.name if build_file else "",
    }
