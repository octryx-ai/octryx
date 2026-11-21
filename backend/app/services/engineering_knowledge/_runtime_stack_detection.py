"""Stack and source-version detection from a repository's metadata and build files."""

from __future__ import annotations

import re
from pathlib import Path

from ...models import CodeRepository

PRUNE_DIRS = {".git", ".idea", ".venv", "node_modules", "target", "build", "dist", "__pycache__"}
_PYTHON_MARKER_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "pytest.ini",
    ".python-version",
    "runtime.txt",
)


def detect_repository_stack_and_versions(repo: CodeRepository) -> tuple[str, dict[str, str]]:
    repo_root = Path(str(repo.repo_root or ""))
    metadata_text = " ".join(
        str(value)
        for source in (repo.capabilities_json or {}, repo.latest_index_summary or {}, repo.config_json or {})
        for value in (source.values() if isinstance(source, dict) else [])
    ).lower()
    files_text = read_stack_files(repo_root)
    combined = f"{metadata_text}\n{files_text}".lower()
    stack_key = ""
    if "spring-boot" in combined or "spring boot" in combined or "org.springframework.boot" in combined:
        stack_key = "java-spring"
    elif "java" in combined or "maven.compiler" in combined or "<artifactid>" in combined:
        stack_key = "java"
    elif "fastapi" in combined:
        stack_key = "python-fastapi"
    elif "python" in combined or _has_python_markers(repo_root):
        stack_key = "python"
    return stack_key, detect_source_versions(files_text)


def read_stack_files(repo_root: Path) -> str:
    if not repo_root.is_dir():
        return ""
    chunks: list[str] = []
    for relative_path in _stack_file_candidates(repo_root):
        path = repo_root / relative_path
        if path.is_file():
            chunks.append(f"\n# file: {relative_path}\n{path.read_text(encoding='utf-8', errors='replace')[:200_000]}")
    return "\n".join(chunks)


def _stack_file_candidates(repo_root: Path) -> list[str]:
    direct_candidates = [
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradle.properties",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "runtime.txt",
        ".python-version",
    ]
    candidates = [relative_path for relative_path in direct_candidates if (repo_root / relative_path).is_file()]
    module_poms = sorted(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.glob("*/pom.xml")
        if path.is_file() and path.parent.name not in PRUNE_DIRS
    )
    for relative_path in module_poms[:20]:
        if relative_path not in candidates:
            candidates.append(relative_path)
    return candidates


def detect_source_versions(text: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for pattern in (
        r"<java\.version>\s*([^<\s]+)\s*</java\.version>",
        r"<maven\.compiler\.release>\s*([^<\s]+)\s*</maven\.compiler\.release>",
        r"sourceCompatibility\s*=\s*['\"]?([^'\"\s]+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            versions["java"] = match.group(1).strip()
            break
    spring_match = (
        re.search(r"<spring-boot\.version>\s*([^<\s]+)\s*</spring-boot\.version>", text, re.IGNORECASE)
        or re.search(
            r"<artifactId>\s*spring-boot-starter-parent\s*</artifactId>\s*<version>\s*([^<\s]+)\s*</version>",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        or re.search(r"org\.springframework\.boot['\"]?\s+version\s+['\"]([^'\"]+)", text, re.IGNORECASE)
    )
    if spring_match:
        versions["spring_boot"] = spring_match.group(1).strip()
    python_match = re.search(r"# file: \.python-version\s*\n\s*([0-9]+(?:\.[0-9]+){0,2})", text, re.IGNORECASE)
    python_match = python_match or re.search(
        r"# file: runtime\.txt\s*\n\s*python-?([0-9]+(?:\.[0-9]+){0,2})",
        text,
        re.IGNORECASE,
    )
    python_match = python_match or re.search(
        r"requires-python\s*=\s*['\"][^'\"]*?([0-9]+(?:\.[0-9]+){0,2})",
        text,
        re.IGNORECASE,
    )
    if python_match:
        versions["python"] = python_match.group(1).strip()
    return versions


def _has_python_markers(repo_root: Path) -> bool:
    return repo_root.is_dir() and any((repo_root / marker).exists() for marker in _PYTHON_MARKER_FILES)
