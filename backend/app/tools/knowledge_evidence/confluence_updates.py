"""``list_confluence_page_updates``: recent Confluence changes, from the Source Sync ledger only."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.sources.sync.confluence_updates import (
    REASON_NEVER_RAN,
    REASON_NOT_CONFIGURED,
    confluence_page_updates,
)
from .._confluence_evidence import with_recorded_page_source
from ..context import ToolContext
from ._scope import authorized_workspace

MESSAGES = {
    REASON_NOT_CONFIGURED: (
        "This Workspace has no Confluence Source Sync connector, so there is no recorded Confluence changes feed."
    ),
    REASON_NEVER_RAN: "The Workspace's Confluence Source Sync has not completed a sync yet.",
    "invalid_request": "days must be 1-90 and limit 1-100.",
}


class ListConfluencePageUpdatesTool:
    name = "list_confluence_page_updates"
    description = "List the Confluence pages new, changed or removed recently, as recorded by the Source Sync."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        result = await confluence_page_updates(
            context.db, authorized, days=params.get("days"), limit=params.get("limit")
        )
        if result["state"] != "ok":
            return {**result, "error": MESSAGES.get(str(result.get("reason")), MESSAGES["invalid_request"])}
        # New and changed pages name their recorded origin link as the citable source (evidence fields).
        for listing in ("new_pages", "changed_pages"):
            pages = result.get(listing)
            if isinstance(pages, list):
                result[listing] = [
                    with_recorded_page_source(page) if isinstance(page, dict) else page for page in pages
                ]
        return result


__all__ = ["ListConfluencePageUpdatesTool"]
