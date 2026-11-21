"""The ``run_test_suite`` tool: runs the detected or declared test suite and remembers its failures per thread."""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from sqlalchemy import select

from app.tools.context import ToolContext

from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_execution_events import build_execution_event


def _thread_quality_signals(thread_context_row: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The thread context payload and its ``quality_signals`` dict (both empty when absent)."""
    payload = (
        dict(thread_context_row.context_json or {})
        if thread_context_row and isinstance(thread_context_row.context_json, dict)
        else {}
    )
    quality_signals = payload.get("quality_signals") if isinstance(payload.get("quality_signals"), dict) else {}
    return payload, quality_signals


async def _load_previous_failed_tests(context: ToolContext) -> tuple[Any, list[str]]:
    """The session's thread context row (or None) and the failures of its last test run."""
    if context.db is None or not context.session_id:
        return None, []
    from ...models import ThreadContext

    thread_context_row = (
        await context.db.execute(select(ThreadContext).where(ThreadContext.session_id == context.session_id))
    ).scalar_one_or_none()
    _payload, quality_signals = _thread_quality_signals(thread_context_row)
    previous_failed_tests = [
        str(item) for item in (quality_signals.get("last_test_failures") or []) if str(item).strip()
    ]
    return thread_context_row, previous_failed_tests


def _test_event_status(result: dict[str, Any], exit_code: int | None) -> str:
    if result.get("error"):
        return "failed"
    if result.get("all_green") is True:
        return "succeeded"
    if exit_code == 0 and result.get("all_green") is not False:
        return "succeeded"
    return "failed"


async def _store_quality_signals(context: ToolContext, thread_context_row: Any, result: dict[str, Any]) -> None:
    from ...models import ThreadContext

    payload, quality_signals = _thread_quality_signals(thread_context_row)
    quality_signals.update(
        {
            "last_test_failures": result.get("failed_tests") or [],
            "last_test_framework": result.get("framework"),
            "last_test_command": result.get("command"),
        }
    )
    payload["quality_signals"] = quality_signals
    if thread_context_row is None:
        thread_context_row = ThreadContext(
            id=str(uuid.uuid4()),
            session_id=context.session_id,
            context_json=payload,
        )
        context.db.add(thread_context_row)
    else:
        thread_context_row.context_json = payload
        thread_context_row.version = int(thread_context_row.version or 1) + 1
    await context.db.flush()


class RunTestSuiteTool:
    name = "run_test_suite"
    description = "Run the detected repository test suite and return a structured result."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        thread_context_row, previous_failed_tests = await _load_previous_failed_tests(context)

        started_at = perf_counter()
        from ...services.workflow_runs.workspace.declared_tests import declared_test_run

        # A server phase of a workflow run runs its repository's declared test command in the run's copy.
        result = await declared_test_run(context, timeout_sec=int(params.get("timeout_sec") or 120),
                                         previous_failed_tests=previous_failed_tests) or await _resolve_test_suite_service()(
            cwd=cwd,
            framework=params.get("framework"),
            path=params.get("path"),
            coverage=bool(params.get("coverage", False)),
            timeout_sec=int(params.get("timeout_sec") or 120),
            previous_failed_tests=previous_failed_tests,
            project_config=context.project_config,
            db=context.db,
        )
        exit_code = result.get("exit_code") if isinstance(result.get("exit_code"), int) else None
        result["execution_event"] = build_execution_event(
            kind="test",
            tool_name=self.name,
            command=result.get("command"),
            cwd=str(result.get("repo_root") or cwd),
            status=_test_event_status(result, exit_code),
            exit_code=exit_code,
            duration_ms=int((perf_counter() - started_at) * 1000),
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            metadata={
                "framework": result.get("framework"),
                "path": result.get("path"),
                "all_green": result.get("all_green"),
                "failed_tests": result.get("failed_tests") or [],
                "validation_blockers": result.get("validation_blockers") or [],
            },
        )
        if context.db is not None and context.session_id and not result.get("error"):
            await _store_quality_signals(context, thread_context_row, result)
        return result


def _resolve_test_suite_service():
    from ...services import code_quality_service

    return code_quality_service.run_test_suite


__all__ = ["RunTestSuiteTool"]
