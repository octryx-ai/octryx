"""Which code-quality settings a repository declares or implies, tried in a fixed order."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from app.services.code_quality.repo_files import (
    CPP_SOURCE_SUFFIXES,
    OPENREWRITE_DEFAULT_MAVEN_PLUGIN_VERSION,
    _iter_repo_files,
    _read_json,
    _repo_has_any,
)


def _explicit_config_payload(repo_root: Path) -> dict[str, Any] | None:
    explicit_path = repo_root / ".octryx-codequality.json"
    if not explicit_path.exists():
        return None
    payload = _read_json(explicit_path)
    if not payload:
        return None
    return {"repo_root": str(repo_root), "source": str(explicit_path), **payload}


def _pyproject_payload(repo_root: Path) -> dict[str, Any] | None:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        payload = {}
    octryx_tool = (((payload.get("tool") or {}).get("octryx")) or {}) if isinstance(payload, dict) else {}
    if not (isinstance(octryx_tool, dict) and isinstance(octryx_tool.get("code_quality"), dict)):
        return None
    return {
        "repo_root": str(repo_root),
        "source": str(pyproject_path),
        **octryx_tool["code_quality"],
    }


def _package_json_payload(repo_root: Path) -> dict[str, Any] | None:
    package_json = repo_root / "package.json"
    if not package_json.exists():
        return None
    payload = _read_json(package_json)
    scripts = payload.get("scripts") or {}
    return {
        "repo_root": str(repo_root),
        "source": str(package_json),
        "test_runner": "npm test" if isinstance(scripts, dict) and scripts.get("test") else "npm test",
        "formatter": "prettier",
        "linter": "eslint",
        "language": "typescript" if (repo_root / "tsconfig.json").exists() else "javascript",
        "sast_runners": ["semgrep"],
    }


def _go_payload(repo_root: Path) -> dict[str, Any] | None:
    if not (repo_root / "go.mod").exists():
        return None
    return {
        "repo_root": str(repo_root),
        "source": str(repo_root / "go.mod"),
        "test_runner": "go test ./...",
        "formatter": "gofmt",
        "linter": "golangci-lint",
        "import_formatter": "goimports",
        "language": "go",
        "sast_runners": ["gosec"],
    }


def _java_payload(repo_root: Path) -> dict[str, Any] | None:
    java_markers = ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"]
    if not any((repo_root / marker).exists() for marker in java_markers):
        return None
    return {
        "repo_root": str(repo_root),
        "source": "auto:java",
        "test_runner": "mvn test" if (repo_root / "pom.xml").exists() else "./gradlew test",
        "formatter": "google-java-format",
        "linter": "checkstyle",
        "language": "java",
        "refactor_tool": "openrewrite",
        "openrewrite_plugin_version": OPENREWRITE_DEFAULT_MAVEN_PLUGIN_VERSION,
        "openrewrite_recipes": [],
        "openrewrite_recipe_artifacts": [],
        "sast_runners": ["semgrep", "spotbugs"],
    }


def _python_payload(repo_root: Path) -> dict[str, Any] | None:
    python_markers = ["pyproject.toml", "requirements.txt", "pytest.ini", "setup.py"]
    if not any((repo_root / marker).exists() for marker in python_markers):
        return None
    return {
        "repo_root": str(repo_root),
        "source": "auto:python",
        "test_runner": "pytest",
        "linter": "ruff",
        "formatter": "ruff",
        "type_checker": "mypy",
        "sast": "bandit",
        "sast_runners": ["bandit"],
        "language": "python",
    }


def _c_family_payload(repo_root: Path) -> dict[str, Any] | None:
    c_markers = ("compile_commands.json", "CMakeLists.txt", "Makefile", "makefile")
    if not (_repo_has_any(repo_root, c_markers) or _iter_repo_files(repo_root, CPP_SOURCE_SUFFIXES, max_files=1)):
        return None
    return {
        "repo_root": str(repo_root),
        "source": "auto:c-family",
        "formatter": "clang-format",
        "linter": "clang-tidy",
        "language": "c",
        "sast_runners": ["semgrep"],
    }


def _unknown_payload(repo_root: Path) -> dict[str, Any]:
    return {
        "repo_root": str(repo_root),
        "source": "auto:unknown",
        "language": "unknown",
    }


# A repository's own declaration wins over the toolchain profile; an inferred kind yields to it.
REPO_LOCAL_DETECTORS = (_explicit_config_payload, _pyproject_payload)
AUTO_DETECTORS = (_package_json_payload, _go_payload, _java_payload, _python_payload, _c_family_payload)
