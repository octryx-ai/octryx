"""Schema of ``list_confluence_page_updates``: the Confluence changes feed of the Source Sync ledger.

No scope property: the Workspace is the run's. The bounds mirror
``services/knowledge/sources/sync/confluence_updates`` (a definition module imports no service).
Merged into ``get_knowledge_evidence_definitions``; a read of the Workspace's own Knowledge ledger,
so it is a built-in read tool, not a Confluence connector call.
"""

from __future__ import annotations

MAX_DAYS = 90
MAX_LIMIT = 100


def get_knowledge_source_update_definitions() -> dict[str, dict]:
    return {
        "list_confluence_page_updates": {
            "type": "function",
            "function": {
                "name": "list_confluence_page_updates",
                "description": (
                    "List the Confluence pages that were new, changed or removed in the last days, as recorded "
                    "by the Workspace's Confluence Source Sync. Read-only; the Workspace is the session's. Each "
                    "page has its title, url, Confluence version and recorded_at (when the platform synced the "
                    "change, not when it was edited); synced_through says how fresh the feed is. Cite pages as "
                    "markdown links [title](url). state needs_configuration means the Workspace has no "
                    "Confluence Source Sync connector (confluence_sync_not_configured) or it never completed a "
                    "sync (confluence_sync_never_ran): say so, and use search_confluence for a live query instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": f"The window in days (1-{MAX_DAYS}).",
                            "default": 7,
                        },
                        "limit": {
                            "type": "integer",
                            "description": f"Maximum pages per list (1-{MAX_LIMIT}).",
                            "default": 50,
                        },
                    },
                    "required": [],
                },
            },
        },
    }


__all__ = ["get_knowledge_source_update_definitions"]
