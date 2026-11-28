"""``run_test_suite`` in a server phase of a workflow run: the repository's declared test command in the run's copy."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.services.code_quality.report_parsers import parse_pytest_failed_tests, parse_pytest_summary

from ...code_quality.helpers import truncate
from ...process_output_redaction import redact_process_output
from ..phase_workspace import RUN_WORKING_COPY_KEY, run_working_copy

_JUNIT = re.compile(r"--junit-?xml[= ](?P<path>\S+)")


def _kept(text: str) -> str:
    return truncate(redact_process_output(text or ""))


def _report_path(root: Path, command: str) -> Path | None:
    match = _JUNIT.search(command)
    if match is None:
        return None
    path = (root / match["path"]).resolve()
    return path if path.is_relative_to(root) else None


def _fresh_report(path: Path | None, started: float, root: Path) -> dict[str, Any]:
    # The path was removed before the run, so only a report present now is this execution's.
    from ...workflow_checks.test_ids import Resolver
    from ...workflow_checks.test_output import parse_junit

    if path is None:
        return {"fresh": False}
    relative = str(path.relative_to(root))
    try:
        if not path.is_file() or path.stat().st_mtime < started - 1:
            return {"path": relative, "fresh": False}
        parsed = parse_junit(path.read_text(encoding="utf-8", errors="replace"), Resolver((), root))
    except OSError:
        return {"path": relative, "fresh": False}
    return {"path": relative, "fresh": True, "format": "junit", **parsed.fields()}


def _not_ready(command: str, root: Path, reason: str) -> dict[str, Any]:
    return {"framework": "declared", "repo_root": str(root), "command": command, "exit_code": 127,
            "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "all_green": False, "stdout": "",
            "stderr": f"{command.split()[0] if command.split() else 'test'}: command not found ({reason})",
            "failed_tests": [], "newly_broken": [], "environment_not_ready": reason}


async def _execute(command: str, *, root: Path, env: dict[str, str], timeout: int, db: Any,
                   project_config: dict[str, Any]) -> tuple[int | None, str, str, dict[str, Any]]:
    # Never a direct host spawn: the configured runtime's limits and fallback rule apply as for every platform command.
    from ... import execution_runtime  # resolved at call time: the module's configured entry
    from ...code_quality.run_status import bounded_command_timeout

    timeout = bounded_command_timeout(timeout)
    result = await execution_runtime.execute_with_runtime(
        db=db, project_config=project_config, command=command, cwd=root, workspace_root=root, timeout_sec=timeout,
        shell=True, env=env)
    metadata = dict(result.metadata or {})
    if result.timed_out:
        return 124, "", f"the test command timed out after {timeout} s", metadata
    return result.exit_code, str(result.stdout or ""), str(result.stderr or ""), metadata


async def declared_environment(db: Any, run: Any) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    from .preparation import preparation
    from .spec import SOURCE_CODING_SETUP, SOURCE_DECLARED, environment_for_run, runtime_environment

    root = run_working_copy(run) if run is not None else None
    if root is None:
        return None
    prepared = preparation(run)
    environment = dict(dict(prepared.get("spec") or {}).get("environment") or {}) or runtime_environment(
        await environment_for_run(db, run))
    if not environment or environment.get("source") not in (SOURCE_DECLARED, SOURCE_CODING_SETUP):
        return None
    return root, environment, prepared


def not_ready_reason(label: str, command: str, root: Path, environment: dict[str, Any],
                     prepared: dict[str, Any]) -> str:
    from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE

    from ...execution_runtime.foreign_build_guard import guard_server_command_in
    from .preparation import STATE_READY
    from .spec import refused_command

    # This copy is on the server: the declared command never runs build/test tooling here. A
    # declared ``path`` (``.venv/bin``) puts the working copy's own executables first on PATH, so even a read-only
    # name (``ruff``, ``git``) would run a file of the repository: refused as well.
    if guard_server_command_in(command, list(environment.get("path") or []), where=f"declared_{label}") is not None:
        return SERVER_BUILD_MESSAGE
    if refused := refused_command(command):
        return f"the declared {label} command is refused: {refused}"
    if prepared and prepared.get("state") != STATE_READY:
        return (f"the run's working folder is not prepared (state {prepared.get('state') or 'unknown'}); run "
                "'Prepare the working folder' again")
    missing = [item for item in (str(entry) for entry in environment.get("path") or []) if not (root / item).is_dir()]
    if missing:
        return (f"the declared environment is not prepared in the run's working copy ({', '.join(missing)} "
                "missing); run 'Prepare the working folder' again")
    return ""


def server_build_refused(db: Any, run: Any, label: str, command: str,
                         environment: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.execution_runtime.build_guard_classify import classify_command
    from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_NOT_ALLOWED

    from ...execution_runtime.foreign_build_guard import repository_path_verdict
    from ..records import record_event
    from ..runtime_target.server_build import EVENT_REFUSED

    judged = classify_command(command)
    if not judged.blocked:
        judged = repository_path_verdict(command, list((environment or {}).get("path") or [])) or judged
    verdict = judged.to_dict()
    if db is not None and run is not None:
        record_event(db, run, EVENT_REFUSED, node_id=run.current_node_id, detail={
            "reason": SERVER_BUILD_NOT_ALLOWED, "where": f"declared_{label}", "command": command[:300],
            "foreign_build_guard": verdict})
    return {"error_code": SERVER_BUILD_NOT_ALLOWED, "foreign_build_guard": verdict}


async def audit_refusal(command: str, where: str) -> None:
    from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_NOT_ALLOWED

    from ...execution_runtime import command_audit

    try:
        await command_audit.record(command, verdict="refused", where=where, reason=SERVER_BUILD_NOT_ALLOWED)
    except command_audit.CommandAuditUnavailableError:
        pass


async def declared_test_run(context: Any, *, timeout_sec: int = 120,
                            previous_failed_tests: list[str] | None = None) -> dict[str, Any] | None:
    from ..records import active_run_for_session
    from .server_prepare import _env

    config = getattr(context, "project_config", None) or {}
    db, session_id = getattr(context, "db", None), getattr(context, "session_id", None)
    if not config.get(RUN_WORKING_COPY_KEY) or db is None or not session_id:
        return None
    run = await active_run_for_session(db, session_id)
    resolved = await declared_environment(db, run)
    if resolved is None:
        return None
    root, environment, prepared = resolved
    command = str(environment.get("test") or "").strip()
    if not command:
        return None
    if reason := not_ready_reason("test", command, root, environment, prepared):
        from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE

        refused = server_build_refused(db, run, "test", command, environment) if reason == SERVER_BUILD_MESSAGE else {}
        if refused:
            await audit_refusal(command, "declared_test")
        return {**_not_ready(command, root, reason), **refused}
    path_dirs = [str(item) for item in environment.get("path") or []]
    report_path = _report_path(root, command)
    if report_path is not None and report_path.exists():
        try:  # an earlier run's report never counts for this one
            report_path.unlink()
        except OSError as error:
            return _not_ready(command, root, f"the earlier test report {report_path.relative_to(root)} could not be "
                                             f"removed ({error.strerror or 'error'}): a fresh one cannot be told apart")
    started = time.time()
    # Exactly the Prepare/readiness environment (server_prepare._env: the declared path first, VIRTUAL_ENV), handed
    # over explicitly to the execution runtime — the runner never inherits the API's interpreter.
    code, stdout, stderr, runtime = await _execute(command, root=root, env=_env(root, path_dirs),
                                                   timeout=max(10, timeout_sec), db=db, project_config=config)
    if code is None:
        # The runtime refused or could not start the runner (no host fallback unless the runtime allows one).
        provider = runtime.get("provider") or runtime.get("requested_provider") or "runtime"
        return {**_not_ready(command, root, f"the execution runtime did not start the declared test command "
                                            f"({provider}): {_kept(stderr)[:300] or 'not started'}"),
                "execution_runtime": runtime, "test_report": {"fresh": False}}
    combined = "\n".join(filter(None, [stdout, stderr]))
    summary = parse_pytest_summary(combined)
    failed = parse_pytest_failed_tests(combined)
    return {
        "framework": "declared", "repo_root": str(root), "command": command, "exit_code": code,
        "passed": summary["passed"], "failed": summary["failed"], "errors": summary["errors"],
        "skipped": summary["skipped"], "coverage_pct": None,
        "all_green": code == 0 and not summary["failed"] and not summary["errors"],
        "stdout": _kept(stdout), "stderr": _kept(stderr), "failed_tests": failed,
        "newly_broken": sorted(set(failed) - set(previous_failed_tests or [])),
        "declared_environment": {"source": environment.get("source"), "path": path_dirs},
        "execution_runtime": runtime,
        # This execution's own JUnit report (canonical ids), the run's preferred evidence; absent → not trusted.
        "test_report": _fresh_report(report_path, started, root),
    }


__all__ = ["audit_refusal", "declared_environment", "declared_test_run", "not_ready_reason", "server_build_refused"]
