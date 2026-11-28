"""The per-language lint and format checks of ``lint_and_format_workspace_impl``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_quality.helpers import (
    command_available,
    detect_validation_blockers,
    format_check_command,
    resolve_c_family_formatter_command,
    resolve_c_family_linter_command,
    resolve_go_formatter_command,
    resolve_java_formatter_command,
    truncate,
)
from app.services.process_output_redaction import redact_process_output

RunExecFn = Callable[..., Awaitable[dict[str, Any]]]
WhichFn = Callable[[str], str | None]


def _kept_report(text: str | None) -> str:
    return truncate(redact_process_output(text or ""), max_chars=3000)


@dataclass
class LintRun:
    config: dict[str, Any]
    repo_root: Path
    auto_fix: bool
    timeout_sec: int
    db: AsyncSession | None
    project_config: dict[str, Any] | None
    run_exec_fn: RunExecFn
    which_fn: WhichFn
    checks: list[dict[str, Any]] = field(default_factory=list)
    auto_fixed: int = 0

    def setting(self, key: str) -> str:
        return str(self.config.get(key) or "").strip().lower()

    async def run_named(self, name: str, command: list[str], category: str) -> None:
        if not command_available(command, self.repo_root, which_fn=self.which_fn):
            self.checks.append(
                {"name": name, "category": category, "status": "skipped", "reason": "tool_not_installed"}
            )
            return
        result = await self.run_exec_fn(
            command,
            cwd=self.repo_root,
            timeout_sec=self.timeout_sec,
            db=self.db,
            project_config=self.project_config,
        )
        status = "passed" if result["exit_code"] == 0 else "failed"
        combined = "\n".join(filter(None, [result.get("stdout", ""), result.get("stderr", "")]))
        if self.auto_fix and status == "passed" and category == "formatter":
            self.auto_fixed += 1
        self.checks.append(
            {
                "name": name,
                "category": category,
                "status": status,
                "command": result["command"],
                "exit_code": result["exit_code"],
                "stdout": _kept_report(result["stdout"]),
                "stderr": _kept_report(result["stderr"]),
                "execution_runtime": result.get("execution_runtime"),
                "validation_blockers": detect_validation_blockers(
                    combined,
                    exit_code=result["exit_code"],
                    tool_name=name,
                    config=self.config,
                ),
            }
        )


async def _python_checks(run: LintRun) -> None:
    formatter = run.setting("formatter")
    auto_fix = run.auto_fix
    await run.run_named("ruff", ["ruff", "check", ".", *(["--fix"] if auto_fix else [])], "linter")
    formatter_command = format_check_command(formatter or "ruff", auto_fix=auto_fix)
    if formatter_command:
        await run.run_named(
            "ruff-format" if formatter == "ruff" else formatter or "formatter", formatter_command, "formatter"
        )
    if run.setting("type_checker") == "mypy":
        await run.run_named("mypy", ["mypy", "."], "type_checker")


async def _javascript_checks(run: LintRun) -> None:
    formatter = run.setting("formatter")
    await run.run_named(run.setting("linter") or "eslint", ["eslint", "."], "linter")
    formatter_command = format_check_command(formatter or "prettier", auto_fix=run.auto_fix)
    if formatter_command:
        await run.run_named(formatter or "prettier", formatter_command, "formatter")


async def _go_checks(run: LintRun) -> None:
    formatter = run.setting("formatter")
    formatter_command = resolve_go_formatter_command(
        run.repo_root, tool_name=formatter or "gofmt", auto_fix=run.auto_fix, which_fn=run.which_fn
    )
    if formatter_command:
        await run.run_named(formatter or "gofmt", formatter_command, "formatter")
    if run.setting("import_formatter") == "goimports":
        import_command = resolve_go_formatter_command(
            run.repo_root, tool_name="goimports", auto_fix=run.auto_fix, which_fn=run.which_fn
        )
        if import_command:
            await run.run_named("goimports", import_command, "formatter")
    await run.run_named(run.setting("linter") or "golangci-lint", ["golangci-lint", "run"], "linter")


async def _java_checks(run: LintRun) -> None:
    repo_root = run.repo_root
    formatter_command = resolve_java_formatter_command(repo_root, auto_fix=run.auto_fix, which_fn=run.which_fn)
    if formatter_command:
        await run.run_named("java-formatter", formatter_command, "formatter")
    if run.setting("linter") != "checkstyle":
        return
    if (repo_root / "gradlew").exists():
        await run.run_named("checkstyle", ["./gradlew", "checkstyleMain", "checkstyleTest"], "linter")
    elif (repo_root / "mvnw").exists():
        await run.run_named("checkstyle", ["./mvnw", "-q", "checkstyle:check"], "linter")
    elif run.which_fn("mvn"):
        await run.run_named("checkstyle", ["mvn", "-q", "checkstyle:check"], "linter")
    elif run.which_fn("gradle"):
        await run.run_named("checkstyle", ["gradle", "checkstyleMain", "checkstyleTest"], "linter")
    else:
        run.checks.append(
            {"name": "checkstyle", "category": "linter", "status": "skipped", "reason": "tool_not_installed"}
        )


async def _c_family_checks(run: LintRun) -> None:
    formatter_command = resolve_c_family_formatter_command(run.repo_root, auto_fix=run.auto_fix, which_fn=run.which_fn)
    if formatter_command:
        await run.run_named("clang-format", formatter_command, "formatter")
    linter_command = resolve_c_family_linter_command(run.repo_root, which_fn=run.which_fn)
    if linter_command:
        await run.run_named("clang-tidy", linter_command, "linter")


LANGUAGE_CHECKS: dict[str, Callable[[LintRun], Awaitable[None]]] = {
    "python": _python_checks,
    "javascript": _javascript_checks,
    "typescript": _javascript_checks,
    "go": _go_checks,
    "java": _java_checks,
    "c": _c_family_checks,
}
