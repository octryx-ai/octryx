"""The one role filter for the chat's tool surface and the octryx client's MCP ``tools/list`` and calls."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .effective import WorkRoleGrant, effective_permission
from .grant_checks import NO_ROLE_EN, connection_refusal, empty_reason, tool_allowed, tool_refusal

TRUSTED_NOTICE = ("Note: one of your roles in this Workspace is trusted. Your chat writes run without a per-call "
                  "confirmation; messages to other people are still confirmed.")


async def chat_turn_grant(db: AsyncSession, *, user_id: str | None, workspace_id: str | None) -> WorkRoleGrant | None:
    if not db or not user_id or not workspace_id:
        return None
    grant = await effective_permission(db, user_id, workspace_id)
    return None if grant.unrestricted else grant


def _name(definition: Any) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    return str((function or {}).get("name") or "").strip() if isinstance(function, dict) else ""


def filter_definitions(definitions: list[dict[str, Any]], grant: WorkRoleGrant | None) -> list[dict[str, Any]]:
    if grant is None:
        return definitions
    return [definition for definition in definitions if tool_allowed(grant, _name(definition))]


def context_grant(context: Any) -> WorkRoleGrant | None:
    grant = getattr(context, "work_role_grant", None)
    return grant if isinstance(grant, WorkRoleGrant) else None


def dispatch_refusal(tool_name: str, context: Any) -> dict[str, Any] | None:
    return tool_refusal(context_grant(context), tool_name)


def write_connection_refusal(tool_name: str, context: Any, connection_id: str | None,
                             connection_label: str = "") -> dict[str, Any] | None:
    from ..named_connections.connection_gate import is_write_tool

    grant = context_grant(context)
    if grant is None or not is_write_tool(tool_name):
        return None
    return connection_refusal(grant, tool_name, connection_id, connection_label)


def trusted_writes(context: Any) -> bool:
    grant = context_grant(context)
    return grant is not None and grant.trusted


def prompt_note(grant: WorkRoleGrant | None) -> str | None:
    if grant is None:
        return None
    if empty_reason(grant):
        return (f"The person has no role in this Workspace, so this chat has no tools. Answer their request by "
                f"telling them, in their language: \"{NO_ROLE_EN}\".")
    return TRUSTED_NOTICE if grant.trusted else None


def with_prompt_note(messages: list[dict[str, Any]], note: str | None) -> list[dict[str, Any]]:
    if not note or not messages or messages[0].get("role") != "system":
        return messages
    first = dict(messages[0])
    content = first.get("content")
    if isinstance(content, str):
        first["content"] = f"{content}\n\n{note}"
    elif isinstance(content, list):
        first["content"] = [*content, {"type": "text", "text": note}]
    else:
        return messages
    return [first, *messages[1:]]


async def mcp_grant(db: AsyncSession, user_id: str | None, workspace_id: str | None) -> WorkRoleGrant | None:
    if not user_id or not workspace_id:
        return None
    grant = await effective_permission(db, user_id, workspace_id)
    return None if grant.unrestricted else grant


__all__ = ["TRUSTED_NOTICE", "chat_turn_grant", "context_grant", "dispatch_refusal", "filter_definitions",
           "mcp_grant", "prompt_note", "trusted_writes", "with_prompt_note", "write_connection_refusal"]
