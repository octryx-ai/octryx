"""The paths a phase of a workflow run never lets its agent change (also for slice children)."""

from __future__ import annotations

import posixpath
import re
import sys
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path

GIT_INTERNAL_NAMES = frozenset({".gitattributes"})
ENVIRONMENT_DIRS = frozenset({".venv", "venv", ".tox", "node_modules", "site-packages", "__pypackages__"})
TEST_DIRS = frozenset({"tests", "test", "testing", "__tests__", "spec", "specs"})
_TEST_FILE = re.compile(r"^(test_.*\.py|.*_test\.py|.*_test\.go|.*\.(test|spec)\.[a-z0-9]+)$")
_CONFIG_FILE = re.compile(
    r"^(conftest\.py|\.?pytest\.(ini|toml|cfg)|pyproject\.toml|setup\.cfg|tox\.ini|sitecustomize\.py|"
    r"usercustomize\.py|.*\.pth|pytest\.py|package\.json|\.babelrc|"
    r"(jest|vitest|vite|babel|karma)\.config\.[a-z0-9.]+|vitest\.workspace\.[a-z0-9.]+|\.mocharc(\.[a-z0-9]+)?|"
    r"go\.mod|go\.work)$")

KIND_GIT = "git_internal"
KIND_ENVIRONMENT = "environment"
KIND_CONFIRMED_TEST = "confirmed_test"
KIND_TEST_FILE = "test_file"
KIND_TEST_CONFIG = "test_config"
KIND_NEW_FILE = "new_file"
KIND_PACKAGING = "packaging"
KIND_SHADOW = "shadows_installed"
_PACKAGING_DIR = re.compile(r".*\.(dist-info|egg-info)$")
_PACKAGING_FILE = re.compile(r"^(entry_points\.txt|.*\.egg-link|.*\.pth|.*\.py[co])$")
IMPORT_ROOTS = frozenset({"src", "lib"})


def fold(path: str) -> str:
    return posixpath.normpath(str(path or "").replace("\\", "/")).lstrip("/").casefold()


def is_test_path(folded: str) -> bool:
    parts = folded.split("/")
    return bool(TEST_DIRS & set(parts[:-1])) or bool(_TEST_FILE.match(parts[-1]))


def import_name(relative: str) -> tuple[str, str] | None:
    parts = fold(relative).split("/")
    index = 1 if parts[0] in IMPORT_ROOTS and len(parts) > 1 else 0
    if index >= len(parts) - 1 and not parts[index].endswith(".py"):
        return None
    name = parts[index].removesuffix(".py")
    return "/".join(parts[:index + 1]), name.replace("-", "_")


def protected_kind(relative: str, *, confirmed_files: Iterable[str], protect_tests: bool, exists: bool | None = True,
                   create: Iterable[str] = (), shadows: bool = False, flat: bool = False,
                   tests_free: bool = False) -> str | None:
    folded = fold(relative)
    parts = folded.split("/")
    if ".git" in parts or parts[-1] in GIT_INTERNAL_NAMES:
        return KIND_GIT
    if ENVIRONMENT_DIRS & set(parts[:-1]):
        return KIND_ENVIRONMENT
    if not protect_tests:
        return None
    if folded in {fold(name) for name in confirmed_files if name}:
        return KIND_CONFIRMED_TEST
    if tests_free and is_test_path(folded):
        return None
    if is_test_path(folded):
        return KIND_TEST_FILE
    if _CONFIG_FILE.match(parts[-1]):
        return KIND_TEST_CONFIG
    if any(_PACKAGING_DIR.match(part) or part == "__pycache__" for part in parts[:-1]) or _PACKAGING_FILE.match(
            parts[-1]):
        return KIND_PACKAGING  # plugin registration (entry points), path hooks and bytecode run before any test
    if exists:
        return None
    if shadows:
        return KIND_SHADOW
    patterns = [fold(pattern) for pattern in create if str(pattern or "").strip()]
    if len(parts) > 1 and any(fnmatchcase(folded, pattern) for pattern in patterns):
        return None
    # A flat repository keeps its modules at the top level, so a new top-level source file is the change itself.
    if flat and len(parts) == 1:
        return None
    return KIND_NEW_FILE


def path_matches(path: str, pattern: str) -> bool:
    return fnmatchcase(path, pattern) or (pattern.startswith("**/") and fnmatchcase(path, pattern[3:]))


def is_flat_repository(copy: object, create: Iterable[str]) -> bool:
    from pathlib import Path

    tops = {str(pattern).strip().split("/", 1)[0] for pattern in create if str(pattern or "").strip()}
    tops = {top for top in tops if top and not any(char in top for char in "*?[")}
    return bool(tops) and not any((Path(str(copy)) / top).is_dir() for top in tops)


_MESSAGES = {
    KIND_GIT: "'{path}' is git's own configuration: no phase of a workflow run changes it.",
    KIND_ENVIRONMENT: "'{path}' is part of an environment whose programs the phase runs: no phase changes it.",
    KIND_TEST_FILE: "'{path}' is a test file: phase '{title}' makes the code pass the confirmed tests and changes "
                    "no test.",
    KIND_TEST_CONFIG: "'{path}' configures a test runner or the interpreter: phase '{title}' never changes how the "
                      "tests run.",
    KIND_PACKAGING: "'{path}' is packaging metadata or bytecode (entry points, .pth, .pyc): phase '{title}' never "
                    "changes what the interpreter loads before the tests.",
    KIND_SHADOW: "'{path}' would start a package named like an installed distribution: phase '{title}' never "
                 "shadows what the tests import.",
    KIND_NEW_FILE: "'{path}' would be a new file: phase '{title}' creates files only under its path_rules.create "
                   "patterns, never at the top level.",
}


CONFIRMED_BY_PERSON, CONFIRMED_BY_RUN = "person", "run"


def protected_message(kind: str, relative: str, title: str, confirmed_by: str = CONFIRMED_BY_PERSON) -> str:
    if kind == KIND_CONFIRMED_TEST:
        from .run_texts import run_text

        key = "protected.confirmed_by_run" if confirmed_by == CONFIRMED_BY_RUN else "protected.confirmed_by_person"
        return run_text(key, path=relative, phase=title)
    return _MESSAGES.get(kind, _MESSAGES[KIND_TEST_CONFIG]).format(path=relative, title=title)


def environment_names(root: Path) -> frozenset[str]:
    names = set(sys.stdlib_module_names)
    for venv in (root / ".venv", root / "venv"):
        for site in venv.glob("lib/python*/site-packages"):
            for entry in site.iterdir():
                if entry.name.endswith((".dist-info", ".egg-info")):
                    top = entry / "top_level.txt"
                    names.update(line.strip() for line in _read_lines(top))
                    names.add(entry.name.split("-", 1)[0])
                elif entry.is_dir() or entry.suffix == ".py":
                    names.add(entry.name.removesuffix(".py"))
    try:
        from importlib.metadata import packages_distributions

        names.update(packages_distributions())
    except Exception:  # noqa: BLE001 - the interpreter's own distributions are an addition, never required
        pass
    return frozenset(name.casefold().replace("-", "_") for name in names if name)


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


def shadows_installed(copy: Path, relative: str, names: frozenset[str]) -> bool:
    found = import_name(relative)
    if found is None:
        return False
    path, name = found
    return name in names and not (copy / path).exists() and not (copy / f"{path}.py").exists()


__all__ = ["CONFIRMED_BY_PERSON", "CONFIRMED_BY_RUN", "KIND_CONFIRMED_TEST", "KIND_ENVIRONMENT", "KIND_GIT",
           "KIND_NEW_FILE", "KIND_PACKAGING", "KIND_SHADOW", "KIND_TEST_CONFIG", "KIND_TEST_FILE",
           "environment_names", "fold", "import_name", "is_test_path", "protected_kind", "protected_message",
           "shadows_installed"]
