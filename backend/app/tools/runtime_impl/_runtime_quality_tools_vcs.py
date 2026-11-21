"""Quality tooling focused on git history: recent commits and diffs of the workspace repository."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from app.tools.context import ToolContext

from ...services.execution_runtime.server_env import with_git_hardening
from ...services.process_output_redaction import redact_process_output
from ...services.request_analysis import effective_limit_from_request_analysis
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_execution_events import build_execution_event, execution_status_from_exit_code


async def _start_git(command: list[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=with_git_hardening(os.environ),  # git runs nothing the working copy configures
    )


def _parse_git_log(stdout_text: str) -> list[dict[str, str]]:
    commits = []
    for line in stdout_text.splitlines():
        if not line.strip():
            continue
        full_hash, short_hash, author_name, author_email, authored_at, subject = (
            line.split("\x1f", 5) + ["", "", "", "", "", ""]
        )[:6]
        commits.append(
            {
                "commit": full_hash,
                "short_commit": short_hash,
                "author_name": author_name,
                "author_email": author_email,
                "authored_at": authored_at,
                "subject": subject,
            }
        )
    return commits


class ListWorkspaceGitCommitsTool:
    name = "list_workspace_git_commits"
    description = "List recent commits from the local workspace git repository using a Python-computed time range."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        days = max(1, min(int(params.get("days") or 5), 90))
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=250,
            hard_max=500,
        )
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}

        cutoff = datetime.now(UTC) - timedelta(days=days)
        command = [
            "git",
            "-C",
            str(cwd),
            "log",
            f"--since={cutoff.isoformat()}",
            f"--max-count={limit}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s",
        ]
        relative_path = str(params.get("path") or "").strip().strip("/")
        if relative_path:
            command.extend(["--", relative_path])

        process = await _start_git(command)
        timeout_sec = int(params.get("timeout_sec") or 20)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {"error": f"git log timed out after {timeout_sec}s", "cwd": str(cwd)}

        stdout_text = stdout.decode("utf-8", errors="replace")
        # Git stderr can carry credentialed remote URLs: never kept, only its size.
        stderr_chars = len(stderr)
        if process.returncode != 0:
            return {
                "error": "git log failed",
                "error_code": "git_log_failed",
                "cwd": str(cwd),
                "exit_code": process.returncode,
                "stderr_chars": stderr_chars,
            }

        commits = _parse_git_log(stdout_text)
        return {
            "cwd": str(cwd),
            "days": days,
            "cutoff_utc": cutoff.isoformat(),
            "path": relative_path or None,
            "commit_count": len(commits),
            "commits": commits,
            "stderr_chars": stderr_chars,
        }


def _git_diff_command(cwd: Path, *, from_ref: str, to_ref: str, path_filter: str, staged: bool,
                      stat_only: bool) -> list[str]:
    command = ["git", "-C", str(cwd), "diff"]
    if staged:
        command.append("--cached")
    if stat_only:
        command.append("--stat")
    if from_ref and to_ref:
        command.extend([f"{from_ref}..{to_ref}"])
    elif from_ref:
        command.extend([f"{from_ref}..HEAD"])
    elif to_ref:
        command.extend([f"HEAD..{to_ref}"])
    if path_filter:
        command.extend(["--", path_filter])
    return command


class GetGitDiffTool:
    name = "get_git_diff"
    description = (
        "Show git diff output for the local workspace repository. "
        "Compares working tree vs HEAD, staged changes, or two commits/branches. "
        "Use from_ref and to_ref for a commit range, or leave both empty for uncommitted changes."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}

        from_ref = str(params.get("from_ref") or "").strip()
        to_ref = str(params.get("to_ref") or "").strip()
        path_filter = str(params.get("path") or "").strip().strip("/")
        staged = bool(params.get("staged", False))
        stat_only = bool(params.get("stat_only", False))
        max_chars = int(params.get("max_chars") or 8000)

        command = _git_diff_command(cwd, from_ref=from_ref, to_ref=to_ref, path_filter=path_filter, staged=staged,
                                    stat_only=stat_only)

        started_at = perf_counter()
        process = await _start_git(command)
        timeout_sec = int(params.get("timeout_sec") or 20)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            process.kill()
            _, timeout_stderr = await process.communicate()
            return self._timeout_result(command, cwd, timeout_sec, timeout_stderr, started_at)

        stdout_text = stdout.decode("utf-8", errors="replace")
        execution_event = self._diff_event(command, cwd, process.returncode, stdout_text, stderr, started_at)
        if process.returncode != 0:
            # Git stderr can carry credentialed remote URLs: the failure keeps only fixed facts.
            return {
                "error": "git diff failed",
                "error_code": "git_diff_failed",
                "cwd": str(cwd),
                "command": command,
                "exit_code": process.returncode,
                "execution_event": execution_event,
            }

        # The diff is the product result the agent asked for: kept, redacted.
        stdout_text = redact_process_output(stdout_text)
        truncated = len(stdout_text) > max_chars
        return {
            "cwd": str(cwd),
            "command": command,
            "exit_code": process.returncode,
            "from_ref": from_ref or None,
            "to_ref": to_ref or None,
            "staged": staged,
            "stat_only": stat_only,
            "path": path_filter or None,
            "diff": stdout_text[:max_chars] + ("\n...[truncated]" if truncated else ""),
            "truncated": truncated,
            "execution_event": execution_event,
        }

    def _diff_event(self, command: list[str], cwd: Path, returncode: int | None, stdout_text: str, stderr: bytes,
                    started_at: float) -> dict[str, Any]:
        stderr_text = stderr.decode("utf-8", errors="replace")
        duration_ms = int((perf_counter() - started_at) * 1000)
        return build_execution_event(
            kind="diff",
            tool_name=self.name,
            command=command,
            cwd=str(cwd),
            status=execution_status_from_exit_code(returncode),
            exit_code=returncode,
            duration_ms=duration_ms,
            stdout=stdout_text,
            stderr=stderr_text,
        )

    def _timeout_result(self, command: list[str], cwd: Path, timeout_sec: int, timeout_stderr: bytes,
                        started_at: float) -> dict[str, Any]:
        stderr_text = timeout_stderr.decode("utf-8", errors="replace")
        duration_ms = int((perf_counter() - started_at) * 1000)
        return {
            "error": f"git diff timed out after {timeout_sec}s",
            "cwd": str(cwd),
            "command": command,
            "exit_code": None,
            "execution_event": build_execution_event(
                kind="diff",
                tool_name=self.name,
                command=command,
                cwd=str(cwd),
                status="timed_out",
                exit_code=None,
                duration_ms=duration_ms,
                stderr=stderr_text,
            ),
        }


__all__ = [
    "ListWorkspaceGitCommitsTool",
    "GetGitDiffTool",
]
