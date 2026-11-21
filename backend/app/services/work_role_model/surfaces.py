"""The one role filter for the chat's tool surface and the octryx client's MCP ``tools/list`` and calls.

Both surfaces enforce: ``offered = governed set ∩ tools of the person's roles ∩ connection
levels ∩ Workspace policy``, and "the same filter applies to the client's MCP tools/list and its dispatch, so chat
and client match for the same person and Workspace". Both surfaces compute :func:`effective_permission` for
(user, Workspace) once per request and ask the same synchronous checks (``grant_checks``).

Only chat turns are filtered on the chat side (``chat_connector_writes`` marks them, ``run_capability.chat_writes``):
workflow-run phases, schedules, flows and sub-agents keep their declared surfaces. Nothing narrows while the
Workspace switch ``role_based_tools`` is off, and platform admins are never filtered.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .effective import WorkRoleGrant, effective_permission
from .grant_checks import NO_ROLE_EN, connection_refusal, empty_reason, tool_allowed, tool_refusal

TRUSTED_NOTICE = ("Note: one of your roles in this Workspace is trusted. Your chat writes run without a per-call "
                  "confirmation; messages to other people are still confirmed.")


async def chat_turn_grant(db: AsyncSession, *, user_id: str | None, workspace_id: str | None) -> WorkRoleGrant | None:
    """The chat turn's grant, ``None`` when nothing narrows (no Workspace, switch off, platform admin)."""
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
    """A chat turn's call outside the person's roles (a model may name a tool it was never offered)."""
    return tool_refusal(context_grant(context), tool_name)


def write_connection_refusal(tool_name: str, context: Any, connection_id: str | None,
                             connection_label: str = "") -> dict[str, Any] | None:
    """Delivery per connection: a write through a connection none of the person's roles is granted."""
    from ..named_connections.connection_gate import is_write_tool

    grant = context_grant(context)
    if grant is None or not is_write_tool(tool_name):
        return None
    return connection_refusal(grant, tool_name, connection_id, connection_label)


def trusted_writes(context: Any) -> bool:
    """A trusted role: the chat's connector and platform writes run without the per-call card (explicit opt-in)."""
    grant = context_grant(context)
    return grant is not None and grant.trusted


def prompt_note(grant: WorkRoleGrant | None) -> str | None:
    """What the chat model must tell the person: no role (and why), or that their writes are trusted."""
    if grant is None:
        return None
    if empty_reason(grant):
        return (f"The person has no role in this Workspace, so this chat has no tools. Answer their request by "
                f"telling them, in their language: \"{NO_ROLE_EN}\".")
    return TRUSTED_NOTICE if grant.trusted else None


def with_prompt_note(messages: list[dict[str, Any]], note: str | None) -> list[dict[str, Any]]:
    """Append ``note`` to the leading system message (string or content blocks); other shapes stay unchanged."""
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
    """The client connection's grant (same function as the chat); ``None`` when nothing narrows."""
    if not user_id or not workspace_id:
        return None
    grant = await effective_permission(db, user_id, workspace_id)
    return None if grant.unrestricted else grant


__all__ = ["TRUSTED_NOTICE", "chat_turn_grant", "context_grant", "dispatch_refusal", "filter_definitions",
           "mcp_grant", "prompt_note", "trusted_writes", "with_prompt_note", "write_connection_refusal"]
