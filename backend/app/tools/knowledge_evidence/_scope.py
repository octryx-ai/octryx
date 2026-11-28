"""The server-owned scope and the fixed answers shared by the Knowledge tools."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.access.authorization import AuthorizedWorkspace, authorize_tool_workspace
from ...services.knowledge.access.bindings import KnowledgeScope, resolve_scope
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ..context import ToolContext

STATE_MESSAGES = {
    "not_found": "No Knowledge workspace is in scope for this session.",
    "denied": "Knowledge evidence access is denied for this workspace.",
    "invalid_request": "The evidence query was empty or outside the supported bounds.",
    "needs_configuration": (
        "Knowledge is not configured on this instance for this request (storage, embedding or graph); "
        "an administrator must configure it."
    ),
    "no_sources": "This workspace has no Knowledge sources yet, so there is nothing to search. Add a source first.",
    "projection_pending": (
        "This workspace's Knowledge sources are not searchable yet: their projection is pending. Try again later."
    ),
    "unavailable": "The Knowledge evidence index is currently unavailable.",
    "contract_violation": "The Knowledge evidence index could not serve this request.",
    "limit_exceeded": "The evidence query exceeded a supported bound.",
    "unsupported_media_type": "The Knowledge evidence index could not serve this request.",
}
FALLBACK_MESSAGE = "The Knowledge evidence index could not serve this request."


def failure(state: str) -> dict[str, Any]:
    return {"error": STATE_MESSAGES.get(state, FALLBACK_MESSAGE), "state": state}


async def authorized_workspace(params: object, context: ToolContext) -> AuthorizedWorkspace | dict[str, Any]:
    if not context.db:
        return {"error": "No active database session", "state": "unavailable"}
    if type(params) is not dict:
        return failure("invalid_request")
    project_id = str((context.project_config or {}).get("project_id") or "").strip() or None
    if project_id is None:
        return failure("not_found")
    try:
        return await authorize_tool_workspace(
            context.db,
            user_id=str(context.user_id),
            project_id=project_id,
            allowed_project_ids=context.project_ids,
        )
    except EvidenceLedgerError as error:
        return failure(error.state.value)


async def knowledge_scope(params: object, context: ToolContext) -> KnowledgeScope | dict[str, Any]:
    authorized = await authorized_workspace(params, context)
    if type(authorized) is dict:
        return authorized
    return await resolve_scope(context.db, authorized)


__all__ = ["FALLBACK_MESSAGE", "STATE_MESSAGES", "authorized_workspace", "failure", "knowledge_scope"]
