"""Local git materialization of a coding workspace: clone, base commit, feature branch checkout."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ...error_facts import error_facts


def _materialize_local_git_workspace(
    *,
    source_root: Path | None,
    workspace_root: Path,
    feature_branch: str,
    base_branch: str,
) -> dict[str, Any]:
    refusal = _materialize_refusal(source_root, workspace_root)
    if refusal is not None:
        return refusal
    commands: list[dict[str, Any]] = []
    if not (workspace_root / ".git").exists():
        clone, _ = _run_git(
            ["git", "clone", "--no-tags", "--branch", base_branch, str(source_root), str(workspace_root)]
        )
        commands.append(clone)
        if clone["exit_code"] != 0:
            return {
                "status": "blocked",
                "base_commit": None,
                "evidence": {"clone_performed": False, "clone_reason": "git_clone_failed", "commands": commands},
            }
    base_commit_result, head_output = _run_git(["git", "rev-parse", "HEAD"], cwd=workspace_root)
    commands.append(base_commit_result)
    feature_ref = feature_branch or f"feature/{workspace_root.name}"
    # A feature branch that already exists in the source repository is the
    # continuation state (redeclared work item after a declined PR): the run
    # resumes on it instead of recreating the branch from the base branch.
    existing_ref, _ = _run_git(
        ["git", "rev-parse", "--verify", "--quiet", f"origin/{feature_ref}"],
        cwd=workspace_root,
    )
    commands.append(existing_ref)
    if existing_ref["exit_code"] == 0:
        checkout, _ = _run_git(["git", "checkout", "-B", feature_ref, f"origin/{feature_ref}"], cwd=workspace_root)
    else:
        checkout, _ = _run_git(["git", "checkout", "-B", feature_ref], cwd=workspace_root)
    commands.append(checkout)
    status = "prepared" if base_commit_result["exit_code"] == 0 and checkout["exit_code"] == 0 else "blocked"
    return {
        "status": status,
        "base_commit": _git_sha(head_output) if base_commit_result["exit_code"] == 0 else None,
        "evidence": {
            "clone_performed": True,
            "clone_reason": "local_git_source_repository",
            "commands": commands,
        },
    }


def _materialize_refusal(source_root: Path | None, workspace_root: Path) -> dict[str, Any] | None:
    """The prepared-empty or blocked result when no clone can start, else ``None``."""
    if source_root is None:
        return {
            "status": "prepared_empty",
            "base_commit": None,
            "evidence": {"clone_performed": False, "clone_reason": "source_repository_root_missing"},
        }
    if not (source_root / ".git").exists():
        return {
            "status": "prepared_empty",
            "base_commit": None,
            "evidence": {"clone_performed": False, "clone_reason": "source_repository_root_is_not_git"},
        }
    if any(workspace_root.iterdir()) and not (workspace_root / ".git").exists():
        return {
            "status": "blocked",
            "base_commit": None,
            "evidence": {"clone_performed": False, "clone_reason": "workspace_path_not_empty"},
        }
    return None


_GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")


def _git_sha(value: str) -> str | None:
    text = str(value or "").strip()
    return text if _GIT_SHA.match(text) else None


def _run_git(argv: list[str], *, cwd: Path | None = None) -> tuple[dict[str, Any], str]:
    """Stored facts for one git command, plus its stdout for the caller's own parsing only.

    Git output can carry credentialed remote URLs and paths, so the stored evidence keeps the
    literal subcommand, the exit status and a closed outcome; the argv (paths) and the
    stdout/stderr are never stored.
    """
    facts: dict[str, Any] = {"git": argv[1] if len(argv) > 1 else "git"}
    try:
        from ...execution_runtime.server_env import with_git_hardening

        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=with_git_hardening(os.environ),  # git runs nothing the working copy configures
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**facts, "exit_code": 127, "outcome": "not_started", **error_facts("git_command_failed", exc)}, ""
    outcome = "succeeded" if completed.returncode == 0 else "failed"
    return {**facts, "exit_code": completed.returncode, "outcome": outcome}, completed.stdout
