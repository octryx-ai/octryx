"""File and folder removal by a changing phase: plain ``rm`` / ``git rm`` of named paths under the path rules."""

from __future__ import annotations

from typing import Any

from app.services.agent_gateway.command_strict import strict_argv

from ...agent_gateway.tool_check import ToolDecision, allowed_by_default, candidate_paths
from ..protected_paths import path_matches
from ..run_texts import run_text
from .phase_rules import _path_decision, _relative
from .tool_denial import PLATFORM_WRITE_TOOLS, REASON_OUTSIDE_PHASE_TOOLS, REASON_PHASE_PATH, _deny

# a phase that splits a module could not delete the old file (rm, git rm and unlink were all
# refused as "not read-only"), so dead files stayed. A changing phase may remove single files of the repository with
# a plain ``rm`` or ``git rm``, or ``git restore`` / ``git checkout --`` of named files: no recursion, no globs, each
# path under the same path rules as an edit.
_REMOVE_FLAGS = {"rm": frozenset({"-f"}), "git rm": frozenset({"-f", "-q", "--quiet"})}
_GLOB_CHARS = frozenset("*?[]{}~")


def removal_paths(command: str) -> list[str] | None:
    """The files a plain single ``rm`` / ``git rm`` removes or ``git restore`` / ``git checkout --`` resets; ``None``
    for any other command."""
    segments = strict_argv(command)
    if not segments or len(segments) != 1:
        return None
    words = list(segments[0])
    if words and words[0] == "rm":
        allowed, args = _REMOVE_FLAGS["rm"], words[1:]
    elif words[:2] == ["git", "rm"]:
        allowed, args = _REMOVE_FLAGS["git rm"], words[2:]
    elif words[:2] == ["git", "restore"]:
        # benchmark T3: the agent had to undo changes in the wrong app and could not; it rewrote the
        # files by hand and broke a test. Restoring named files to the commit is a change like an edit.
        allowed, args = frozenset(), words[2:]
    elif words[:3] == ["git", "checkout", "--"]:
        allowed, args = frozenset(), words[3:]
    else:
        return None
    flags = [word for word in args if word.startswith("-")]
    paths = [word for word in args if not word.startswith("-")]
    if not paths or any(flag not in allowed for flag in flags) or any(set(path) & _GLOB_CHARS for path in paths):
        return None
    if any(path.rstrip("/") in ("", ".", "..") or path.endswith("/") for path in paths):
        return None  # the whole tree or a folder: never one named file
    return paths


# A changing phase may remove a whole folder with ``rm -r`` / ``git rm -r`` when it is generated (these names, anywhere
# in the repository) or lies wholly inside the phase's own paths (a ``<folder>/**`` path rule covers it).
_RECURSIVE_FLAGS = {"rm": frozenset({"-r", "-R", "-rf", "-fr", "-Rf", "-fR", "-f", "--recursive", "--force"}),
                    "git rm": frozenset({"-r", "-f", "-q", "--quiet", "--cached", "-rf", "-fr", "-rq", "-qr"})}
GENERATED_DIRS = frozenset({"__pycache__", "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                            "test-reports", ".eggs"})


def recursive_removal_paths(command: str) -> list[str] | None:
    """The folders a single ``rm -r`` / ``git rm -r`` of named paths removes; ``None`` for any other command."""
    segments = strict_argv(command)
    if not segments or len(segments) != 1:
        return None
    words = list(segments[0])
    if words and words[0] == "rm":
        allowed, args = _RECURSIVE_FLAGS["rm"], words[1:]
    elif words[:2] == ["git", "rm"]:
        allowed, args = _RECURSIVE_FLAGS["git rm"], words[2:]
    else:
        return None
    flags = [word for word in args if word.startswith("-")]
    paths = [word.rstrip("/") for word in args if not word.startswith("-")]
    if not paths or any(flag not in allowed for flag in flags) or not any("r" in flag.lower() for flag in flags):
        return None
    if any(set(path) & _GLOB_CHARS or path in ("", ".", "..") or path.startswith("/") or ".." in path.split("/")
           or path.split("/")[0] == ".git" for path in paths):
        return None
    return paths


def generated_dir(path: str) -> bool:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name in GENERATED_DIRS or name.endswith(".egg-info")


def tracked_only_removal(command: str) -> bool:
    """``git rm -r`` without ``-f``: git removes only tracked files, refuses files with uncommitted changes and can
    restore all of them; untracked files stay ("git can undo it" holds for tracked files
    only)."""
    segments = strict_argv(command)
    if not segments or len(segments) != 1 or list(segments[0][:2]) != ["git", "rm"]:
        return False
    return not any(word.startswith("-") and not word.startswith("--") and "f" in word
                   or word == "--force" for word in segments[0][2:])


def _folder_decision(phase: dict[str, Any], folders: list[str], cwd: str, root: str | None,
                     *, tracked_only: bool = False, defaults: dict[str, Any] | None = None) -> ToolDecision | None:
    """``None`` when the phase may change files and every folder is generated or wholly inside its own paths; by
    default (``tool_defaults.shell: free``) also a tracked-only ``git rm -r`` of any folder in the repository."""
    allowed = set(phase["tools"].get("allow") or []) - set(phase["tools"].get("deny") or [])
    if not allowed & PLATFORM_WRITE_TOOLS:
        return _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.no_write_tools", phase=phase["title"]))
    patterns = list(phase["path_rules"].get("write") or [])
    for folder in folders:
        candidates = candidate_paths(folder, cwd)[-1:]
        relative = _relative(candidates[0], root) if candidates else None
        if relative is None or relative in (".", "") or relative.startswith(".."):
            return _deny(REASON_PHASE_PATH, run_text("block.path_outside", path=folder))
        inside = bool(patterns) and all(any(path_matches(probe, pattern) for pattern in patterns)
                                        for probe in (f"{relative}/octryx-probe", f"{relative}/octryx/probe"))
        if not generated_dir(relative) and not inside:
            if tracked_only and defaults is not None and defaults.get("shell") != "strict":
                continue  # logged as allowed by default below
            return _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.folder_removal", target=folder,
                                                              phase=phase["title"]))
    if tracked_only and defaults is not None and not all(generated_dir(folder) for folder in folders):
        return allowed_by_default("shell")
    return None


def _removal_decision(phase: dict[str, Any], paths: list[str], cwd: str, root: str | None) -> ToolDecision | None:
    """``None`` when the phase may change files and every path is a removable file of the repository."""
    allowed = set(phase["tools"].get("allow") or []) - set(phase["tools"].get("deny") or [])
    if not allowed & PLATFORM_WRITE_TOOLS:
        return _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.no_write_tools", phase=phase["title"]))
    for path in paths:
        candidates = candidate_paths(path, cwd)[-1:]
        if not candidates or _relative(candidates[0], root) is None:
            return _deny(REASON_PHASE_PATH, run_text("block.path_outside", path=path))
        refused = _path_decision(phase, {"file_path": path}, cwd, root,
                                 {"target_exists": True, "shadows_installed": False})
        if refused is not None:
            return refused
    return None
