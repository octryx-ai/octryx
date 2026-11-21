"""Command parsing helpers shared by CLI runtime tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SHELL_CONTROL_OPERATOR_PATTERN = re.compile(r"(\&\&|\|\||[|;<>])|\$\(|`")


def contains_shell_control_operators(command: str) -> bool:
    return bool(SHELL_CONTROL_OPERATOR_PATTERN.search(command))


def command_likely_writes_workspace(argv: list[str]) -> bool:
    if not argv:
        return False
    command = argv[0].lower()
    subcommand = argv[1].lower() if len(argv) > 1 else ""
    if command in {"mkdir", "touch", "tee", "cp", "mv", "rm"}:
        return True
    if command in {"python", "python3", "node", "perl", "sed"}:
        return True
    if command == "git":
        return subcommand in {
            "init",
            "clone",
            "apply",
            "am",
            "checkout",
            "switch",
            "branch",
            "commit",
            "merge",
            "stash",
            "reset",
            "clean",
            "pull",
            "push",
            "add",
        }
    if command in {"npm", "pnpm", "yarn"}:
        return subcommand in {"install", "add", "init", "create"}
    if command == "mvn":
        return any("apply" in part.lower() or "format" in part.lower() for part in argv[1:])
    if command == "gradle":
        return any("apply" in part.lower() or "format" in part.lower() for part in argv[1:])
    return False


def command_resolution_error(
    *,
    command: str,
    cwd: Path,
    resolution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not resolution:
        return None
    if resolution.get("script") and "resolved_path" not in resolution:
        candidate_count = int(resolution.get("candidate_count") or 0)
        if candidate_count > 1:
            candidates = [str(item) for item in (resolution.get("candidates") or [])]
            return {
                "error": (
                    f"Referenced script `{resolution['script']}` is ambiguous across the allowed workspace context. "
                    "Specify the repository or cwd explicitly."
                    + (f" Candidates: {', '.join(candidates)}" if candidates else "")
                ),
                "command": command,
                "cwd": str(cwd),
                "script_resolution": resolution,
            }
        return {
            "error": (
                f"Referenced script `{resolution['script']}` was not found in the current working "
                "directory or anywhere in the workspace."
            ),
            "command": command,
            "cwd": str(cwd),
            "script_resolution": resolution,
        }

    repo_resolution = resolution.get("repo_resolution")
    if isinstance(repo_resolution, dict):
        candidate_count = int(repo_resolution.get("candidate_count") or 0)
        if candidate_count > 1 and not repo_resolution.get("resolved_repo_root"):
            repo_candidates = [str(item) for item in (repo_resolution.get("repo_candidates") or [])]
            return {
                "error": (
                    "Command matches multiple allowed repositories. Specify the repository or cwd explicitly."
                    + (f" Candidates: {', '.join(repo_candidates)}" if repo_candidates else "")
                ),
                "command": command,
                "cwd": str(cwd),
                "script_resolution": resolution,
            }
    return None
