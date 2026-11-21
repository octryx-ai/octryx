from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog

MAX_AUDIT_ARG_PREVIEW_ITEMS = 20
MAX_AUDIT_TEXT_LENGTH = 500


def _short_text(value: Any) -> str:
    return str(value if value is not None else "")[:MAX_AUDIT_TEXT_LENGTH]


def _argument_preview(tool_args: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for index, (key, value) in enumerate((tool_args or {}).items()):
        if index >= MAX_AUDIT_ARG_PREVIEW_ITEMS:
            preview["_truncated"] = True
            break
        if isinstance(value, str):
            preview[str(key)] = _short_text(value)
        elif isinstance(value, bool | int | float) or value is None:
            preview[str(key)] = value
        elif isinstance(value, list):
            preview[str(key)] = [_short_text(item) for item in value[:MAX_AUDIT_ARG_PREVIEW_ITEMS]]
        elif isinstance(value, dict):
            preview[str(key)] = {str(child_key): _short_text(child_value) for child_key, child_value in value.items()}
        else:
            preview[str(key)] = _short_text(value)
    return preview


def guard_audit_action(decision: dict[str, Any]) -> str:
    action = str(decision.get("action") or "block").strip().lower()
    if action == "audit":
        return "agent.guard.audit_matched"
    if action == "review":
        return "agent.guard.review_required"
    return "agent.guard.blocked"


async def audit_custom_tool_guard_decision(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str | None,
    message_id: str | None,
    tool_call_id: str | None,
    request_id: str | None,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
    decision: dict[str, Any],
) -> None:
    rule = decision.get("rule") if isinstance(decision.get("rule"), dict) else {}
    db.add(
        AuditLog(
            user_id=user_id,
            session_id=session_id,
            action=guard_audit_action(decision),
            resource_type="exec_policy_guard",
            resource_id=str(decision.get("guard_id") or rule.get("id") or ""),
            details={
                "guard_id": str(decision.get("guard_id") or rule.get("id") or ""),
                "guard_label": str(decision.get("label") or rule.get("label") or ""),
                "guard_action": str(decision.get("action") or rule.get("action") or "block"),
                "guard_severity": str(decision.get("severity") or rule.get("severity") or "medium"),
                "guard_reason": str(decision.get("reason") or rule.get("description") or ""),
                "tool_name": str(tool_name or ""),
                "capability_type": str(capability_type or ""),
                "message_id": str(message_id or ""),
                "tool_call_id": str(tool_call_id or ""),
                "request_id": str(request_id or ""),
                "matched_guard": decision.get("matched_guard") or {},
                "tool_args_preview": _argument_preview(tool_args),
            },
        )
    )
    await db.flush()


__all__ = ["audit_custom_tool_guard_decision", "guard_audit_action"]
