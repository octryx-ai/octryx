from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_quality.helpers import (
    SAST_RUNNER_COMMANDS,
    detect_validation_blockers,
    resolve_sast_runners,
    resolve_validation_gates,
)
from app.services.code_quality.lint_languages import LANGUAGE_CHECKS, LintRun, _kept_report

RunExecFn = Callable[..., Awaitable[dict[str, Any]]]
WhichFn = Callable[[str], str | None]


async def lint_and_format_workspace_impl(
    *,
    cwd: Path,
    auto_fix: bool = False,
    include_sast: bool = True,
    timeout_sec: int = 120,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    load_config_fn: Callable[..., dict[str, Any]],
    run_exec_fn: RunExecFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    config = load_config_fn(cwd, project_config=project_config)
    repo_root = Path(str(config.get("repo_root") or cwd)).resolve()
    language = str(config.get("language") or "unknown").lower()
    validation_gates = resolve_validation_gates(config)
    run = LintRun(
        config=config,
        repo_root=repo_root,
        auto_fix=auto_fix,
        timeout_sec=timeout_sec,
        db=db,
        project_config=project_config,
        run_exec_fn=run_exec_fn,
        which_fn=which_fn,
    )
    language_checks = LANGUAGE_CHECKS.get(language)
    if language_checks is None:
        return {
            "error": "No supported lint/format configuration detected",
            "config": config,
            "repo_root": str(repo_root),
        }
    await language_checks(run)

    if include_sast:
        for runner in resolve_sast_runners(config):
            command = SAST_RUNNER_COMMANDS.get(runner)
            if command:
                await run.run_named(runner, command, "sast")
            else:
                run.checks.append(
                    {"name": runner, "category": "sast", "status": "skipped", "reason": "unsupported_runner"}
                )

    checks = run.checks
    return {
        "repo_root": str(repo_root),
        "config": config,
        "checks": checks,
        "auto_fix": auto_fix,
        "auto_fixed": run.auto_fixed,
        "validation_gates": validation_gates,
        "validation_blockers": _collect_validation_blockers(checks),
        "all_clean": all(item["status"] in {"passed", "skipped"} for item in checks),
        "failed_checks": [item["name"] for item in checks if item["status"] == "failed"],
    }


async def _sast_check(
    runner: str,
    command: list[str],
    *,
    config: dict[str, Any],
    repo_root: Path,
    timeout_sec: int,
    db: AsyncSession | None,
    project_config: dict[str, Any] | None,
    run_exec_fn: RunExecFn,
) -> dict[str, Any]:
    result = await run_exec_fn(
        command,
        cwd=repo_root,
        timeout_sec=timeout_sec,
        db=db,
        project_config=project_config,
    )
    combined = "\n".join(filter(None, [result.get("stdout", ""), result.get("stderr", "")]))
    return {
        "name": runner,
        "category": "sast",
        "status": "passed" if result["exit_code"] == 0 else "failed",
        "command": result["command"],
        "exit_code": result["exit_code"],
        "stdout": _kept_report(result["stdout"]),
        "stderr": _kept_report(result["stderr"]),
        "execution_runtime": result.get("execution_runtime"),
        "validation_blockers": detect_validation_blockers(
            combined,
            exit_code=result["exit_code"],
            tool_name=runner,
            config=config,
        ),
    }


async def run_sast_suite_impl(
    *,
    cwd: Path,
    timeout_sec: int = 120,
    runners: list[str] | None = None,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    load_config_fn: Callable[..., dict[str, Any]],
    run_exec_fn: RunExecFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    config = load_config_fn(cwd, project_config=project_config)
    repo_root = Path(str(config.get("repo_root") or cwd)).resolve()
    validation_gates = resolve_validation_gates(config)
    selected_runners = [
        str(item).strip().lower() for item in (runners or resolve_sast_runners(config)) if str(item).strip()
    ]
    if not selected_runners:
        return {
            "repo_root": str(repo_root),
            "config": config,
            "checks": [],
            "all_clean": True,
            "failed_checks": [],
            "selected_runners": [],
            "validation_gates": validation_gates,
            "validation_blockers": [],
        }

    checks: list[dict[str, Any]] = []
    for runner in selected_runners:
        command = SAST_RUNNER_COMMANDS.get(runner)
        if not command:
            checks.append({"name": runner, "category": "sast", "status": "skipped", "reason": "unsupported_runner"})
            continue
        if not which_fn(command[0]):
            checks.append({"name": runner, "category": "sast", "status": "skipped", "reason": "tool_not_installed"})
            continue
        checks.append(await _sast_check(
            runner, command, config=config, repo_root=repo_root, timeout_sec=timeout_sec, db=db,
            project_config=project_config, run_exec_fn=run_exec_fn,
        ))

    return {
        "repo_root": str(repo_root),
        "config": config,
        "checks": checks,
        "all_clean": all(item["status"] in {"passed", "skipped"} for item in checks),
        "failed_checks": [item["name"] for item in checks if item["status"] == "failed"],
        "selected_runners": selected_runners,
        "validation_gates": validation_gates,
        "validation_blockers": _collect_validation_blockers(checks),
    }


def _collect_validation_blockers(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for check in checks:
        for blocker in check.get("validation_blockers") or []:
            key = (str(blocker.get("code") or ""), str(blocker.get("tool_name") or ""))
            if key in seen:
                continue
            seen.add(key)
            blockers.append(blocker)
    return blockers
