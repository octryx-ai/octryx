"""Shared helpers for cloud connector tools."""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ..context import ToolContext
from .common import _normalize_string_list


def _aws_allowed(context: ToolContext, service: str) -> bool:
    allowed = _normalize_string_list(context.project_config.get("aws_allowed_services"))
    return not allowed or service in allowed


def _gcp_allowed(context: ToolContext, service: str) -> bool:
    allowed = _normalize_string_list(context.project_config.get("gcp_allowed_services"))
    return not allowed or service in allowed


# A connector's command never runs without an end (a git push of a 40 MB story without a
# timeout held the step on a stalled transfer until a person retried it). git also stops a transfer that moves less
# than 1 KB/s for two minutes; the step then fails and is retried (a commit made before stays and is pushed then).
SUBPROCESS_TIMEOUT_SECONDS = 1800
GIT_LOW_SPEED = {"GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "120"}
TIMED_OUT_EXIT = 124


async def _run_subprocess(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = SUBPROCESS_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    from .git_errors import run_with_retry

    return await run_with_retry(_run_subprocess_once, command, env=env, cwd=cwd, timeout=timeout)


async def _run_subprocess_once(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = SUBPROCESS_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    if command and command[0] == "git":
        env = {**(env if env is not None else os.environ), **GIT_LOW_SPEED}
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        return TIMED_OUT_EXIT, "", f"{command[0]} timed out after {int(timeout)} s"
    return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


async def _maybe_block_connector_action_with_approval(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    title: str,
    summary: str,
    details: list[str] | None = None,
) -> dict[str, Any] | None:
    if await consume_change_preview_grant(
        context.db,
        session_id=context.session_id,
        tool_name=tool_name,
        payload=params,
        context=context,
    ):
        return None
    if context.db is None or not context.user_id:
        return None
    preview_payload = {
        "kind": "cloud_action",
        "title": title,
        "summary": summary,
        "details": details or [],
        "toolName": tool_name,
    }
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve cloud change for {tool_name}",
        reason=summary,
    )
    preview = await upsert_change_preview(
        context.db,
        tool_name=tool_name,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(tool_name, params),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }
