from __future__ import annotations

import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_quality.helpers import (
    detect_validation_blockers,
    resolve_gradle_command,
    resolve_maven_command,
    resolve_validation_gates,
    truncate,
)
from app.services.code_quality.report_parsers import (
    parse_go_failed_tests,
    parse_maven_test_summary,
    parse_pytest_failed_tests,
    parse_pytest_summary,
    parse_surefire_reports,
)
from app.services.code_quality.run_status import run_outcome_fields
from app.services.process_output_redaction import redact_process_output

RunExecFn = Callable[..., Awaitable[dict[str, Any]]]
WhichFn = Callable[[str], str | None]


def _kept_output(text: str | None) -> str:
    return truncate(redact_process_output(text or ""))


@dataclass(frozen=True)
class _SuiteRun:
    config: dict[str, Any]
    detected_framework: str
    repo_root: Path
    relative_path: str
    validation_gates: list[dict[str, Any]]
    previous_failed_tests: list[str] | None
    timeout_sec: int
    db: AsyncSession | None
    project_config: dict[str, Any] | None
    run_exec_fn: RunExecFn
    which_fn: WhichFn

    async def run(self, command: list[str]) -> dict[str, Any]:
        return await self.run_exec_fn(
            command,
            cwd=self.repo_root,
            timeout_sec=self.timeout_sec,
            db=self.db,
            project_config=self.project_config,
        )


def _combined(result: dict[str, Any]) -> str:
    return "\n".join(filter(None, [result.get("stdout", ""), result.get("stderr", "")]))


def _head(suite: _SuiteRun, framework: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "framework": framework,
        "repo_root": str(suite.repo_root),
        "path": suite.relative_path,
        "command": result["command"],
        "exit_code": result["exit_code"],
    }


def _tail(suite: _SuiteRun, result: dict[str, Any], combined: str, failed_tests: list[str] | None) -> dict[str, Any]:
    return {
        "stdout": _kept_output(result["stdout"]),
        "stderr": _kept_output(result["stderr"]),
        "failed_tests": failed_tests if failed_tests is not None else [],
        "newly_broken": (
            sorted(set(failed_tests) - set(suite.previous_failed_tests or [])) if failed_tests is not None else []
        ),
        "execution_runtime": result.get("execution_runtime"),
        "validation_gates": suite.validation_gates,
        "validation_blockers": detect_validation_blockers(
            combined,
            exit_code=result["exit_code"],
            tool_name="run_test_suite",
            config=suite.config,
        ),
    }


def _unparsed_counts(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
        "coverage_pct": None,
        "all_green": result["exit_code"] == 0,
    }


async def _run_pytest(suite: _SuiteRun, coverage: bool) -> dict[str, Any]:
    which_fn = suite.which_fn
    python_cmd = sys.executable or which_fn("python3") or which_fn("python")
    command = [python_cmd, "-m", "pytest", suite.relative_path, "-q"]
    if coverage:
        command.extend(["--cov=.", "--cov-report=term"])
    result = await suite.run(command)
    combined = _combined(result)
    coverage_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", combined)
    summary = parse_pytest_summary(combined)
    failed_tests = parse_pytest_failed_tests(combined)
    return {
        **_head(suite, "pytest", result),
        "passed": summary["passed"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "skipped": summary["skipped"],
        "coverage_pct": int(coverage_match.group(1)) if coverage_match else None,
        "all_green": result["exit_code"] == 0 and summary["failed"] == 0 and summary["errors"] == 0,
        **_tail(suite, result, combined, failed_tests),
    }


async def _run_go(suite: _SuiteRun) -> dict[str, Any]:
    result = await suite.run(["go", "test", "./..."])
    failed = len(re.findall(r"^FAIL\t", result["stdout"], re.MULTILINE))
    passed = len(re.findall(r"^ok\t", result["stdout"], re.MULTILINE))
    failed_tests = parse_go_failed_tests(result["stdout"])
    combined = _combined(result)
    return {
        **_head(suite, "go", result),
        "passed": passed,
        "failed": failed,
        "errors": 0,
        "skipped": 0,
        "coverage_pct": None,
        "all_green": result["exit_code"] == 0 and failed == 0,
        **_tail(suite, result, combined, failed_tests),
    }


async def _run_npm(suite: _SuiteRun) -> dict[str, Any]:
    result = await suite.run(["npm", "test", "--", "--runInBand"])
    combined = _combined(result)
    return {**_head(suite, "npm", result), **_unparsed_counts(result), **_tail(suite, result, combined, None)}


async def _run_maven(suite: _SuiteRun) -> dict[str, Any] | None:
    launcher = resolve_maven_command(suite.repo_root, which_fn=suite.which_fn)
    if not launcher:
        return None
    result = await suite.run([*launcher, "-q", "test"])
    combined = _combined(result)
    summary = parse_surefire_reports(suite.repo_root)
    if summary["passed"] == 0 and summary["failed"] == 0 and summary["errors"] == 0 and summary["skipped"] == 0:
        summary = parse_maven_test_summary(combined)
    return {
        **_head(suite, "maven", result),
        # A timed-out or refused build carries ``error``: the gates read it as unrunnable.
        **run_outcome_fields(result),
        "passed": summary["passed"],
        "failed": summary["failed"],
        "errors": summary["errors"],
        "skipped": summary["skipped"],
        "coverage_pct": None,
        "all_green": result["exit_code"] == 0 and summary["failed"] == 0 and summary["errors"] == 0,
        **_tail(suite, result, combined, None),
    }


async def _run_gradle(suite: _SuiteRun) -> dict[str, Any] | None:
    launcher = resolve_gradle_command(suite.repo_root, which_fn=suite.which_fn)
    if not launcher:
        return None
    result = await suite.run([*launcher, "test"])
    combined = _combined(result)
    return {
        **_head(suite, "gradle", result),
        **run_outcome_fields(result),
        **_unparsed_counts(result),
        **_tail(suite, result, combined, None),
    }


def _wants_maven(suite: _SuiteRun) -> bool:
    return suite.detected_framework in {"mvn test", "maven", "java"} or (
        suite.config.get("language") == "java" and (suite.repo_root / "pom.xml").exists()
    )


def _wants_gradle(suite: _SuiteRun) -> bool:
    return suite.detected_framework in {"./gradlew test", "gradle"} or (
        suite.config.get("language") == "java"
        and any((suite.repo_root / marker).exists() for marker in ("build.gradle", "build.gradle.kts"))
    )


async def _run_detected_suite(suite: _SuiteRun, coverage: bool) -> dict[str, Any] | None:
    framework, which_fn = suite.detected_framework, suite.which_fn
    if framework in {"pytest", ""} and (which_fn("pytest") or which_fn("python3") or which_fn("python")):
        return await _run_pytest(suite, coverage)
    if framework in {"go test ./...", "go"} and which_fn("go"):
        return await _run_go(suite)
    if framework in {"npm test", "npm"} and which_fn("npm"):
        return await _run_npm(suite)
    if _wants_maven(suite) and (result := await _run_maven(suite)) is not None:
        return result
    if _wants_gradle(suite) and (result := await _run_gradle(suite)) is not None:
        return result
    return None


async def run_test_suite_impl(
    *,
    cwd: Path,
    framework: str | None = None,
    path: str | None = None,
    coverage: bool = False,
    timeout_sec: int = 120,
    previous_failed_tests: list[str] | None = None,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    load_config_fn: Callable[..., dict[str, Any]],
    run_exec_fn: RunExecFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    config = load_config_fn(cwd, project_config=project_config)
    detected_framework = (framework or str(config.get("test_runner") or "")).strip().lower()
    repo_root = Path(str(config.get("repo_root") or cwd)).resolve()
    relative_path = str(path or ".").strip() or "."
    validation_gates = resolve_validation_gates(config)
    suite = _SuiteRun(
        config=config,
        detected_framework=detected_framework,
        repo_root=repo_root,
        relative_path=relative_path,
        validation_gates=validation_gates,
        previous_failed_tests=previous_failed_tests,
        timeout_sec=timeout_sec,
        db=db,
        project_config=project_config,
        run_exec_fn=run_exec_fn,
        which_fn=which_fn,
    )
    result = await _run_detected_suite(suite, coverage)
    if result is not None:
        return result
    return {
        "error": "No supported test runner detected",
        "repo_root": str(repo_root),
        "detected_test_runner": detected_framework or None,
        "config": config,
        "validation_gates": validation_gates,
    }
