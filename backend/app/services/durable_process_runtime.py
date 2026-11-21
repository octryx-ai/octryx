"""Durable process runtime for long-running command execution."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RuntimeProcess
from ..time_utils import utc_now
from .durable_process_output import _bounded_text, _bounded_timeout, _terminal_status, serialize_runtime_process
from .error_facts import error_text
from .execution_runtime.process_tree import KILL_EXIT_GRACE_SEC, kill_process_tree
from .persistent_process_runtime import spawn_persistent_stdio_process

TERMINAL_PROCESS_STATUSES = {"completed", "failed", "timed_out", "cancelled", "orphaned"}

_async_session_factory: Callable[[], Any] | None = None


@dataclass
class _LiveRuntimeProcess:
    process: Any
    task: asyncio.Task[None]
    cancel_requested: bool = False


_live_processes: dict[str, _LiveRuntimeProcess] = {}


def configure_durable_process_runtime(session_factory: Callable[[], Any] | None) -> None:
    global _async_session_factory
    _async_session_factory = session_factory


async def start_runtime_process(
    db: AsyncSession,
    *,
    command: list[str],
    cwd: Path,
    workspace_root: Path,
    user_id: str | None = None,
    session_id: str | None = None,
    project_id: str | None = None,
    project_config: Mapping[str, Any] | None = None,
    tool_name: str = "start_runtime_process",
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    timeout_seconds = _bounded_timeout(timeout_seconds)
    process_record = RuntimeProcess(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
        tool_name=tool_name,
        cwd=str(cwd.resolve()),
        workspace_root=str(workspace_root.resolve()),
        status="starting",
        timeout_seconds=timeout_seconds,
        timeout_at=utc_now() + timedelta(seconds=timeout_seconds),
    )
    process_record.command = command
    db.add(process_record)
    await db.flush()

    try:
        handle = await spawn_persistent_stdio_process(
            db=db,
            project_config=project_config or {},
            command=command,
            cwd=cwd,
            workspace_root=workspace_root,
            new_process_group=True,
            restricted_env=True,
        )
    except Exception as exc:
        process_record.status = "failed"
        process_record.error = error_text("runtime_process_spawn_failed", exc)
        process_record.completed_at = utc_now()
        process_record.updated_at = utc_now()
        await db.commit()
        return serialize_runtime_process(process_record)

    process_record.status = "running"
    process_record.os_pid = int(getattr(handle.process, "pid", 0) or 0) or None
    process_record.provider = str(handle.metadata.get("provider") or "host")
    process_record.runtime_metadata = handle.metadata
    process_record.updated_at = utc_now()
    await db.commit()
    await db.refresh(process_record)

    task = asyncio.create_task(_watch_process(process_record.id, handle.process, timeout_seconds))
    _live_processes[process_record.id] = _LiveRuntimeProcess(process=handle.process, task=task)
    return serialize_runtime_process(process_record)


async def poll_runtime_process(
    db: AsyncSession,
    *,
    process_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    process_record = await _get_runtime_process(db, process_id, user_id=user_id)
    if process_record is None:
        return {"error": "Runtime process not found", "process_id": process_id}
    if process_record.status == "running" and process_id not in _live_processes:
        process_record.status = "orphaned"
        process_record.error = "Live process handle is unavailable in this runtime instance."
        process_record.completed_at = utc_now()
        process_record.updated_at = utc_now()
        await db.commit()
        await db.refresh(process_record)
    return serialize_runtime_process(process_record)


async def collect_runtime_process(
    db: AsyncSession,
    *,
    process_id: str,
    user_id: str | None = None,
    wait_seconds: int = 0,
) -> dict[str, Any]:
    live = _live_processes.get(process_id)
    if live is not None and wait_seconds > 0 and not live.task.done():
        try:
            await asyncio.wait_for(asyncio.shield(live.task), timeout=max(0, wait_seconds))
        except TimeoutError:
            pass
    return await poll_runtime_process(db, process_id=process_id, user_id=user_id)


async def cancel_runtime_process(
    db: AsyncSession,
    *,
    process_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    process_record = await _get_runtime_process(db, process_id, user_id=user_id)
    if process_record is None:
        return {"error": "Runtime process not found", "process_id": process_id}
    if process_record.status in TERMINAL_PROCESS_STATUSES:
        return serialize_runtime_process(process_record)

    live = _live_processes.get(process_id)
    process_record.cancel_requested_at = utc_now()
    process_record.updated_at = utc_now()
    if live is None:
        process_record.status = "orphaned"
        process_record.error = "Live process handle is unavailable in this runtime instance."
        process_record.completed_at = utc_now()
        await db.commit()
        await db.refresh(process_record)
        return serialize_runtime_process(process_record)

    live.cancel_requested = True
    kill_process_tree(live.process, sig=signal.SIGTERM)
    await db.commit()
    await db.refresh(process_record)
    return serialize_runtime_process(process_record)


async def _watch_process(process_id: str, process: Any, timeout_seconds: int) -> None:
    live = _live_processes.get(process_id)
    try:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
            status = _terminal_status(process.returncode, cancel_requested=bool(live and live.cancel_requested))
            error = None
        except TimeoutError:
            # The whole group dies; the partial output is drained for a bounded grace period only,
            # because a descendant that left the group can hold the pipes open indefinitely.
            kill_process_tree(process)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=KILL_EXIT_GRACE_SEC)
            except TimeoutError:
                stdout, stderr = b"", b""
            status = "timed_out"
            error = f"Runtime process timed out after {timeout_seconds}s"
        await _persist_process_completion(
            process_id,
            status=status,
            exit_code=getattr(process, "returncode", None),
            stdout=stdout,
            stderr=stderr,
            error=error,
        )
    except asyncio.CancelledError:
        # The watcher itself is cancelled (runtime shutdown): the process must not run on unsupervised.
        kill_process_tree(process)
        raise
    finally:
        _live_processes.pop(process_id, None)


async def _persist_process_completion(
    process_id: str,
    *,
    status: str,
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    error: str | None,
) -> None:
    session_factory = _async_session_factory
    if session_factory is None:
        return
    async with session_factory() as db:
        process_record = await _get_runtime_process(db, process_id)
        if process_record is None:
            return
        stdout_text, stdout_truncated = _bounded_text(stdout)
        stderr_text, stderr_truncated = _bounded_text(stderr)
        process_record.status = status
        process_record.exit_code = exit_code
        process_record.stdout_tail = stdout_text
        process_record.stderr_tail = stderr_text
        process_record.output_truncated = stdout_truncated or stderr_truncated
        process_record.error = error
        process_record.completed_at = utc_now()
        process_record.updated_at = utc_now()
        await db.commit()


async def _get_runtime_process(
    db: AsyncSession,
    process_id: str,
    *,
    user_id: str | None = None,
) -> RuntimeProcess | None:
    statement = select(RuntimeProcess).where(RuntimeProcess.id == process_id)
    if user_id:
        statement = statement.where(RuntimeProcess.user_id == user_id)
    return (await db.execute(statement.execution_options(populate_existing=True))).scalar_one_or_none()


__all__ = [
    "TERMINAL_PROCESS_STATUSES",
    "cancel_runtime_process",
    "collect_runtime_process",
    "configure_durable_process_runtime",
    "poll_runtime_process",
    "start_runtime_process",
]
