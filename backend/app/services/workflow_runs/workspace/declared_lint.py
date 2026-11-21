"""The repository's declared lint command, run on the run's copy before the change moves on.

Without it, tests first, implement, the review and the push could pass and then CI fail
on lint — ``flake8`` E501 in the new test helper. The repository declares its lint command (``environment.lint``,
e.g. ``flake8 .``), but no phase or gate of the run ever ran it: the first lint the change met was CI's.

A phase or gate that declares the closed check ``lint_passed`` gets this command's fresh result as its evidence
(``TurnEvidence.lint``):

- run exactly like the declared test command (``declared_tests``): verbatim, in the run's working copy, through the
  platform's execution runtime with the declared ``path`` first on ``PATH`` — the same environment resolution and
  readiness reasons, never the API's interpreter and never a direct host spawn; the output is this execution's;
- judged on **the run's change**: exit 0 passes; otherwise the ``file:line[:col]: message`` findings are kept for the
  files the run changed against its base (``git diff --name-only <base>`` plus new untracked files), so tests first
  answers for its new test files and the gate for the whole change. Findings only in files the run did not touch
  pass with a note; a failing command whose output names no finding fails (nothing is assumed clean);
- a runner that could not start (not prepared, a declared ``path`` missing, exit 126/127, command not found, the
  linter's module missing) is the environment's: the phase turn and the gate pause ``environment_not_ready`` — never
  a pass, never a loop.

No declared lint command, a run whose copy is not on this server (a device run lints on the device) or a slice
turn: ``None`` — the check is not applicable and decides nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .declared_tests import (
    _execute,
    _kept,
    audit_refusal,
    declared_environment,
    not_ready_reason,
    server_build_refused,
)

LINT_CHECK = "lint_passed"
SOURCE = "declared_lint"
MAX_FINDINGS = 20
_FINDING = re.compile(r"^(?:\./)?(?P<file>[^\s:][^:\n]*?):(?P<line>\d+)(?::\d+)?:?\s+(?P<message>\S.*)$")


def _findings(text: str) -> list[dict[str, Any]]:
    found = []
    for line in text.splitlines():
        match = _FINDING.match(line.strip())
        if match:
            found.append({"file": match["file"].replace("\\", "/"), "line": int(match["line"]),
                          "message": match["message"].strip()[:200]})
    return found


def _relative(root: Path, file: str) -> str | None:
    """A finding's file as the canonical path relative to the copy (absolute or relative), ``None`` outside it."""
    try:
        path = Path(file).expanduser()
        resolved = (path if path.is_absolute() else root / path).resolve()
        return resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


async def _changed_files(root: Path, base: str) -> set[str] | None:
    """The files the run changed against its base (tracked and new), or ``None`` when git cannot tell."""
    from .. import safe_git

    if not base:
        return None
    code, changed, _err = await safe_git.git(root, "diff", "--name-only", base, "--")
    untracked_code, untracked, _err = await safe_git.git(root, "ls-files", "--others", "--exclude-standard")
    if code != 0 or untracked_code != 0:
        return None
    return {line.strip() for line in [*changed.splitlines(), *untracked.splitlines()] if line.strip()}


def _environment(command: str, root: Path, reason: str, **extra: Any) -> dict[str, Any]:
    return {"state": "environment", "command": command, "repo_root": str(root), "reason": reason, **extra}


async def declared_lint_run(db: Any, run: Any, *, project_config: dict[str, Any] | None = None,
                            timeout_sec: int = 120) -> dict[str, Any] | None:
    """The declared lint command's fresh result on the run's copy, or ``None`` (nothing to lint here)."""
    from ...project.service import get_project_config
    from ...workflow_checks.test_command_outcome import runner_not_started
    from ..phase_workspace import _on_server
    from .server_prepare import _env

    if run is None or not await _on_server(db, run):
        return None  # a device run lints on the device
    resolved = await declared_environment(db, run)
    if resolved is None:
        return None
    root, environment, prepared = resolved
    command = str(environment.get("lint") or "").strip()
    if not command:
        return None
    if reason := not_ready_reason("lint", command, root, environment, prepared):
        from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE

        refused = server_build_refused(db, run, "lint", command, environment) if reason == SERVER_BUILD_MESSAGE else {}
        if refused:
            from ...execution_runtime.command_audit import run_actor

            with run_actor(db, run, tool_name="lint_passed"):
                await audit_refusal(command, "declared_lint")
        return _environment(command, root, reason, **refused)
    config = project_config if project_config is not None else await get_project_config(run.project_id, db)
    path_dirs = [str(item) for item in environment.get("path") or []]
    from ...execution_runtime.command_audit import run_actor

    with run_actor(db, run, tool_name="lint_passed"):  # a lint gate acts as the run requester
        code, stdout, stderr, runtime = await _execute(command, root=root, env=_env(root, path_dirs),
                                                       timeout=max(10, timeout_sec), db=db, project_config=config)
    text = "\n".join(filter(None, [stdout, stderr]))
    not_started = runner_not_started(text, code, command) if code is not None else (
        f"the execution runtime did not start the declared lint command: {_kept(stderr)[:300] or 'not started'}")
    if not_started:
        return _environment(command, root, not_started, exit_code=code, excerpt=_kept(text)[-1200:],
                            execution_runtime=runtime)
    result = {"command": command, "repo_root": str(root), "exit_code": code, "output": _kept(text)[-4000:],
              "execution_runtime": runtime}
    if code == 0:
        return {**result, "state": "passed"}
    findings = _findings(text)
    if not findings:
        return {**result, "state": "failed", "reason": f"the declared lint command `{command}` failed (exit {code}) "
                                                       f"without file findings: {_kept(text)[-300:]}"}
    changed = await _changed_files(root, str(dict(run.context or {}).get("base_sha") or ""))
    unmapped = [item for item in findings if _relative(root, item["file"]) is None]
    if unmapped:  # a finding the copy cannot place is never read as "outside the change"
        return {**result, "state": "failed", "findings": unmapped[:MAX_FINDINGS],
                "reason": f"`{command}` reports findings outside the run's working copy or at unknown paths: "
                          + "; ".join(f"{item['file']}:{item['line']}" for item in unmapped[:MAX_FINDINGS])}
    own = [item for item in findings if changed is None or _relative(root, item["file"]) in changed]
    if not own:
        return {**result, "state": "passed", "findings": findings[:MAX_FINDINGS],
                "note": f"{len(findings)} lint finding(s) only in files this run did not change"}
    listed = "; ".join(f"{item['file']}:{item['line']}: {item['message']}" for item in own[:MAX_FINDINGS])
    return {**result, "state": "failed", "findings": own[:MAX_FINDINGS],
            "reason": f"`{command}` reports {len(own)} finding(s) in this run's change: {listed}"}


def environment_failure(lint: dict[str, Any] | None) -> dict[str, Any] | None:
    """The run's environment failure for a lint runner that could not start (``readiness.pause_not_ready``)."""
    if not lint or lint.get("state") != "environment":
        return None
    return {"kind": "environment", "reason": str(lint.get("reason") or "the linter could not start"),
            "command": str(lint.get("command") or ""), "exit_code": lint.get("exit_code"),
            "excerpt": str(lint.get("excerpt") or ""), "source": SOURCE}


def declares_lint(checks: list[Any]) -> bool:
    return any(isinstance(check, dict) and check.get("type") == LINT_CHECK for check in checks or [])


async def with_turn_lint(db: Any, evidence: Any, *, request_analysis: dict[str, Any] | None) -> Any:
    """A run phase turn's evidence with the declared lint's fresh result (and its environment failure)."""
    from ....models import WorkflowRun
    from ..binding import run_marker

    marker = run_marker(request_analysis)
    if marker is None or marker.get("slice"):
        return evidence  # chat outside a run, or a slice child in its own worktree
    run = await db.get(WorkflowRun, str(marker["run_id"]))
    evidence.lint = await declared_lint_run(db, run) if run is not None else None
    evidence.environment_failure = evidence.environment_failure or environment_failure(evidence.lint)
    return evidence


__all__ = ["LINT_CHECK", "SOURCE", "declared_lint_run", "declares_lint", "environment_failure", "with_turn_lint"]
