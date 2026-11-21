"""Tool results through the content check before they reach a model.

``content_checked`` is the last step of ``registry.execute_tool`` and ``execute_tool_with_plugins``: every tool
result of a chat turn or an MCP call is asked as ``receive_tool_result`` (``content_routing.tool_results``) for
the context's Workspace, session (the chat conversation) and principal. A masked result replaces the original
(so the stored tool call keeps the masked text, too) and carries ``content_policy`` with the counts; a blocked
one becomes a refusal payload. MCP server tools (``mcp__<server>__<tool>``) have origin ``mcp``, every other tool
``connector``.

A Knowledge retrieval result then gets its retrieved text fenced as untrusted data, citation fields outside
(``services/content_security/knowledge_fence``): both functions are the last step before
the model reads it, in the chat and run loops and on the MCP server.
"""

from __future__ import annotations

from typing import Any

from ..services.classification_tool_policy import tool_connector_family
from ..services.content_routing.conversation_state import CHAT_CONVERSATION
from ..services.content_routing.tool_results import check_tool_result
from ..services.content_security.knowledge_fence import fence_knowledge_result
from ..services.policy_engine.schema import ORIGIN_CONNECTOR, ORIGIN_MCP
from .context import ToolContext

MCP_PREFIX = "mcp__"


def _workspace(context: ToolContext) -> str | None:
    config = context.project_config if isinstance(context.project_config, dict) else {}
    chosen = config.get("project_id") or (context.project_ids[0] if context.project_ids else None)
    return str(chosen) if chosen else None


async def content_checked(tool_name: str, result: Any, context: ToolContext) -> Any:
    return fence_knowledge_result(tool_name, await _content_checked(tool_name, result, context))


async def _content_checked(tool_name: str, result: Any, context: ToolContext) -> Any:
    outcome = await check_tool_result(
        result, tool_name=tool_name, family=tool_connector_family(tool_name),
        origin=ORIGIN_MCP if tool_name.startswith(MCP_PREFIX) else ORIGIN_CONNECTOR,
        workspace_id=_workspace(context), session_id=context.session_id or None, conversation=CHAT_CONVERSATION,
    )
    if outcome.notice and not outcome.blocked and isinstance(outcome.result, dict):
        return {**outcome.result, "content_policy": dict(outcome.notice)}
    return outcome.result


async def mcp_result_checked(tool_name: str, result: dict[str, Any], workspace_id: Any) -> dict[str, Any]:
    """A result of the Octryx MCP server (``mcp_governed_knowledge`` / ``mcp_parity_dispatch``) before it
    goes to the coding agent: origin ``mcp``, the caller's Workspace, no chat conversation."""
    if not isinstance(workspace_id, str):
        return result  # a refusal before any tool ran
    return fence_knowledge_result(tool_name, await _mcp_content_checked(tool_name, result, workspace_id))


async def _mcp_content_checked(tool_name: str, result: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    outcome = await check_tool_result(
        result, tool_name=tool_name, family=tool_connector_family(tool_name), origin=ORIGIN_MCP,
        workspace_id=workspace_id, session_id=None, conversation=CHAT_CONVERSATION,
    )
    if outcome.notice and not outcome.blocked and isinstance(outcome.result, dict):
        return {**outcome.result, "content_policy": dict(outcome.notice)}
    return outcome.result


__all__ = ["content_checked", "mcp_result_checked"]
