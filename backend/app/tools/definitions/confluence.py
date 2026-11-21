"""Tool definitions for confluence domain."""

from __future__ import annotations

import copy

CONFLUENCE_DEFINITIONS: dict[str, dict] = {
    "list_confluence_pages": {
        "type": "function",
        "function": {
            "name": "list_confluence_pages",
            "description": "List Confluence pages available to the current project",
            "parameters": {
                "type": "object",
                "properties": {
                    "space_key": {"type": "string"},
                    "limit": {"type": "integer"},
                    "include_versions": {"type": "boolean"},
                },
            },
        },
    },
    "get_confluence_page": {
        "type": "function",
        "function": {
            "name": "get_confluence_page",
            "description": "Read an allowed Confluence page by id or title",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "title": {"type": "string"},
                    "space_key": {"type": "string"},
                    "expected_instance": {
                        "type": "string",
                        "description": "Run only on this Confluence instance (normalized "
                        "base URL); else an instance_mismatch error, no request",
                    },
                    "expected_connection": {"type": "string", "description": "Run only on this connection id "
                                            "(default or a named connection); else connection_mismatch"},
                },
            },
        },
    },
    "search_confluence": {
        "type": "function",
        "function": {
            "name": "search_confluence",
            "description": "Search Confluence pages by full text or CQL query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text search query"},
                    "cql": {"type": "string", "description": "Explicit CQL query (overrides query)"},
                    "space_key": {"type": "string", "description": "Restrict to a specific space"},
                    "include_child_summary": {
                        "type": "boolean",
                        "description": "Include bounded child-page context for each result when structure matters",
                    },
                    "child_limit": {
                        "type": "integer",
                        "description": "Max child pages per result when include_child_summary is true",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10, max 25)"},
                },
            },
        },
    },
    "create_confluence_page": {
        "type": "function",
        "function": {
            "name": "create_confluence_page",
            "description": "Create a new page in an allowed Confluence space",
            "parameters": {
                "type": "object",
                "properties": {
                    "space_key": {"type": "string", "description": "Target space key"},
                    "title": {"type": "string", "description": "Page title"},
                    "content": {
                        "type": "string",
                        "description": "Page body — Confluence Storage Format HTML or plain text",
                    },
                    "parent_id": {"type": "string", "description": "Optional parent page ID for nesting"},
                    "expected_instance": {
                        "type": "string",
                        "description": "Run only on this Confluence instance (normalized "
                        "base URL); else an instance_mismatch error, no request",
                    },
                    "expected_connection": {"type": "string", "description": "Run only on this connection id "
                                            "(default or a named connection); else connection_mismatch"},
                },
                "required": ["space_key", "title"],
            },
        },
    },
    "update_confluence_page": {
        "type": "function",
        "function": {
            "name": "update_confluence_page",
            "description": "Update an existing Confluence page's content or title",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "title": {"type": "string", "description": "Used to find the page if page_id not known"},
                    "space_key": {"type": "string"},
                    "content": {"type": "string", "description": "New body content (replaces current)"},
                    "new_title": {"type": "string", "description": "Rename the page to this title"},
                    "expected_version": {"type": "integer", "description": "Update only if the page is at "
                                         "this version (compare-and-set); else a version_conflict error"},
                    "expected_instance": {
                        "type": "string",
                        "description": "Run only on this Confluence instance (normalized "
                        "base URL); else an instance_mismatch error, no request",
                    },
                    "expected_connection": {"type": "string", "description": "Run only on this connection id "
                                            "(default or a named connection); else connection_mismatch"},
                },
            },
        },
    },
    "add_confluence_comment": {
        "type": "function",
        "function": {
            "name": "add_confluence_comment",
            "description": "Add a comment to a Confluence page",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "body": {"type": "string", "description": "Comment text"},
                },
                "required": ["page_id", "body"],
            },
        },
    },
}


def get_confluence_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for confluence tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(CONFLUENCE_DEFINITIONS)
