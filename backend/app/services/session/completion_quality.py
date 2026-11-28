"""Completion quality checks for chat run finalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolCall


async def latest_failed_test_validation_summary(
    db: AsyncSession,
    *,
    session_id: str,
    created_at_or_after: datetime | None = None,
) -> dict[str, Any] | None:
    query = select(ToolCall).where(ToolCall.session_id == session_id, ToolCall.tool_name == "run_test_suite")
    if created_at_or_after is not None:
        query = query.where(ToolCall.created_at >= created_at_or_after)
    row = (
        await db.execute(
            query.order_by(ToolCall.created_at.desc(), ToolCall.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None or str(row.status or "").strip().lower() != "success":
        return None
    result = row.result if isinstance(row.result, dict) else {}
    if result.get("all_green") is True:
        return None
    exit_code = result.get("exit_code")
    if result.get("all_green") is False or (isinstance(exit_code, int) and exit_code != 0):
        command = result.get("command")
        return {
            "tool_call_id": row.id,
            "command": command if isinstance(command, (list, str)) else None,
            "exit_code": exit_code,
            "passed": result.get("passed"),
            "failed": result.get("failed"),
            "errors": result.get("errors"),
        }
    return None


__all__ = ["latest_failed_test_validation_summary"]


async def unverified_verification_contract_summary(
    db: AsyncSession,
    *,
    session_id: str,
    session_metadata: dict[str, Any] | None,
    created_at_or_after: datetime | None = None,
) -> dict[str, Any] | None:
    # Guards both claims, done and nothing to do: a no-op claim still requires a passing ``run_validation_commands``.
    execution = (session_metadata or {}).get("secure_work_execution")
    contract = execution.get("verification_contract") if isinstance(execution, dict) else None
    commands = list((contract or {}).get("commands") or []) if isinstance(contract, dict) else []
    if not commands:
        return None
    query = select(ToolCall).where(
        ToolCall.session_id == session_id, ToolCall.tool_name == "run_validation_commands"
    )
    if created_at_or_after is not None:
        query = query.where(ToolCall.created_at >= created_at_or_after)
    row = (
        await db.execute(query.order_by(ToolCall.created_at.desc(), ToolCall.id.desc()).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return {
            "reason": "verification_contract_not_run",
            "detail": (
                "The approved verification contract was never executed this turn. "
                "Run run_validation_commands and reach all_green=true before concluding "
                "(also required for no-op claims)."
            ),
            "command_count": len(commands),
        }
    result = row.result if isinstance(row.result, dict) else {}
    if result.get("all_green") is True:
        return None
    failing = [
        entry.get("command")
        for entry in (result.get("results") or [])
        if isinstance(entry, dict) and not entry.get("ok")
    ]
    return {
        "reason": "verification_contract_failed",
        "detail": "The latest run_validation_commands execution was not all_green.",
        "failing_commands": [c for c in failing if c][:10],
        "tool_call_id": row.id,
    }
