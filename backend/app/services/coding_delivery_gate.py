"""Delivery gate: governed coding runs deliver only a proven contract. A completion claim does not satisfy it; step
instructions are prompts, this gate is the enforcement."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from ..models import Session as ChatSession
from ..models import ToolCall
from .prompt_catalog.out_of_turn import render_prompt_for_scope

logger = logging.getLogger(__name__)

VALIDATION_TOOL_NAME = "run_validation_commands"


def _delivery_gated_tools() -> tuple[str, ...]:
    from .workflow_contracts.agent_definition import ALL_CODING_DELIVERY_TOOLS

    return ALL_CODING_DELIVERY_TOOLS


async def enforce_coding_delivery_validation(
    tool_name: str,
    context: Any,
) -> dict[str, Any] | None:
    if tool_name not in _delivery_gated_tools():
        return None
    db = getattr(context, "db", None)
    session_id = getattr(context, "session_id", None)
    if db is None or not session_id:
        return None
    try:
        session = await db.get(ChatSession, session_id)
        metadata = dict(getattr(session, "metadata_", None) or {}) if session else {}
        execution = metadata.get("secure_work_execution")
        if not isinstance(execution, dict):
            return None
        contract = execution.get("verification_contract")
        if not (isinstance(contract, dict) and contract.get("commands")):
            return None
        if await _has_all_green_validation(db, session_id):
            return None
    except Exception:
        logger.exception("coding_delivery_gate_check_failed session_id=%s", session_id)
        return None
    logger.warning(
        "coding_delivery_blocked_validation_missing session_id=%s tool=%s",
        session_id,
        tool_name,
    )
    return {
        "error": "delivery_blocked_validation_missing",
        "status": "needs_validation",
        # Tool dispatch also serves MCP calls outside a turn: render for the session's Workspace then.
        "detail": await render_prompt_for_scope(
            db, "secure_work.delivery.validation_missing", workspace_id=getattr(session, "project_id", None)
        ),
    }


async def delivery_step_advance_blocked(
    db: Any,
    *,
    session_id: str | None,
    source_step_type: str,
    target_allowed_tools: set[str],
) -> bool:
    # The step machine advances on a tool of the next step, so entering delivery needs the same all-green proof as
    # running it.
    if str(source_step_type or "").strip().lower() != "tdd_cycle":
        return False
    if not target_allowed_tools.intersection(_delivery_gated_tools()):
        return False
    if db is None or not session_id:
        return False
    try:
        blocked = not await _has_all_green_validation(db, session_id)
    except Exception:
        logger.exception("delivery_step_advance_check_failed session_id=%s", session_id)
        return False
    if blocked:
        logger.warning("coding_delivery_step_advance_blocked session_id=%s", session_id)
    return blocked


async def _has_all_green_validation(db: Any, session_id: str) -> bool:
    rows = (
        await db.execute(
            select(ToolCall.result)
            .where(
                ToolCall.session_id == session_id,
                ToolCall.tool_name == VALIDATION_TOOL_NAME,
            )
            .order_by(ToolCall.created_at.desc())
            .limit(1)
        )
    ).scalars().all()
    for result in rows:
        payload = result if isinstance(result, dict) else {}
        if payload.get("all_green") and not payload.get("error"):
            return True
    return False


__all__ = ["delivery_step_advance_blocked", "enforce_coding_delivery_validation"]
