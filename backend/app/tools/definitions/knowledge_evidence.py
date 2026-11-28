"""Schemas of the governed Knowledge tools, led by the one ``knowledge_search``."""

from __future__ import annotations

import copy

from ...services.prompt_catalog.tool_descriptions import CITATION_RULE
from .knowledge_episode import get_knowledge_episode_definitions
from .knowledge_source_updates import get_knowledge_source_update_definitions
from .knowledge_structured import get_knowledge_structured_definitions

MAX_TOOL_RESULT_LIMIT = 20
# Mirrors services/knowledge/ledger/reading.MAX_READ_WINDOW (a definition module imports no service).
MAX_READ_WINDOW = 3

KNOWLEDGE_SEARCH_DESCRIPTION = (
    # The chat sends this schema on every model call; what the result itself says
    # (mode_states, an explicit no-index state, cite_as on every passage) is not repeated here.
    "Search the Workspace's governed Knowledge by keywords and by meaning (also across languages); returns cited "
    "passages. Read-only. Use knowledge_read on a hit for the surrounding paragraphs. Words match whole and "
    "case-insensitive, no wildcards; several words are combined with OR. With exactly one product and a version, changes adds "
    "that product's cited change facts up to the version. Cite a passage by copying its cite_as link; never invent or "
    "guess a URL. " + CITATION_RULE
)


KNOWLEDGE_EVIDENCE_DEFINITIONS: dict[str, dict] = {
    "knowledge_search": {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": KNOWLEDGE_SEARCH_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Terms to search for. Treated as data, never as query syntax.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum passages to return (1-{MAX_TOOL_RESULT_LIMIT}).",
                        "default": 8,
                    },
                    "products": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional product keys (e.g. spring-boot) the user named or results showed.",
                    },
                    "version": {
                        "type": "string",
                        "description": "Optional, with products: one product version (e.g. 4.0).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "knowledge_changes": {
        "type": "function",
        "function": {
            "name": "knowledge_changes",
            "description": (
                "List what changed in one product between two versions (for example spring-boot from 3.5 to "
                "4.0): cited facts extracted from the Workspace's release notes and migration guides, such as "
                "new baselines, removed or renamed APIs and properties, and changed defaults. Read-only; the "
                "Workspace is the session's. Use it for 'what changed' and migration questions, then "
                "knowledge_search or knowledge_read for details. Without query, facts are one page "
                "ordered by kind (REQUIRES and REMOVED first) and spread across the documents' sections; "
                "kind_counts gives the totals, so say how many changes of each kind exist and call again with "
                "query (e.g. Jackson, security, properties) to go deeper on a topic. state not_extracted means the "
                "sources exist but were never extracted into the graph; say so instead of answering from "
                "memory. Each fact names its source (S1, …); cite it by copying that source's cite_as markdown link "
                "from "
                "sources; never invent a URL. " + CITATION_RULE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product key, e.g. spring-boot."},
                    "to_version": {
                        "type": "string",
                        "description": "The target version or release line, e.g. 4.0 (4 means every 4.x release).",
                    },
                    "from_version": {
                        "type": "string",
                        "description": (
                            "Optional: the version upgraded from (exclusive), e.g. 3.5; 3 excludes every 3.x release."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional: rank the facts by this topic (e.g. Jackson, security).",
                    },
                    "limit": {"type": "integer", "description": "Maximum facts (1-200).", "default": 20},
                    "changes_only": {
                        "type": "boolean",
                        "description": (
                            "Default true: only typed changes (REMOVED, RENAMED, REPLACED_BY, DEPRECATED, "
                            "REQUIRES, MOVED_TO, DEFAULT_CHANGED, INTRODUCED). false also lists other facts."
                        ),
                        "default": True,
                    },
                },
                "required": ["product", "to_version"],
            },
        },
    },
    "knowledge_code_impact": {
        "type": "function",
        "function": {
            "name": "knowledge_code_impact",
            "description": (
                "Cite affected files using impact.links at the recorded commit alongside each change-fact source; "
                "migration-guide links alone do not locate code impact. Find where a product version change "
                "applies in the session's repository checkout or the Workspace's repository sources, for a "
                "migration or upgrade (for example spring-boot from 3.5 to 4.0). Joins the Workspace's cited "
                "change facts with the checkout's imports, annotations, configuration keys, dependencies and "
                "Java level; every item has the exact file and line and its source. Read-only. Use it before "
                "changing code in an upgrade, and cite each applied change by copying its source's cite_as link. "
                "commit names the checked-out commit. state not_extracted means the change facts were never "
                "extracted; say so."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product key, e.g. spring-boot."},
                    "to_version": {"type": "string", "description": "The target version, e.g. 4.0."},
                    "from_version": {"type": "string", "description": "Optional: the current version, e.g. 3.5."},
                    "path": {
                        "type": "string",
                        "description": "Optional: repository directory inside the workspace (default: the root).",
                    },
                    "repository": {
                        "type": "string",
                        "description": "Optional: the Workspace repository source to read, as listed under "
                        "repositories when the answer is needs_clarification.",
                    },
                },
                "required": ["product", "to_version"],
            },
        },
    },
    "knowledge_read": {
        "type": "function",
        "function": {
            "name": "knowledge_read",
            "description": (
                "Read a passage returned by knowledge_search together with the neighbouring "
                "paragraphs of the same source revision, to answer from its full context. Read-only; the "
                "Workspace is the session's. Cite it like the search result: [source_title](source_url). "
                "If current is false, the source has a newer revision; say so."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "evidence_key": {
                        "type": "string",
                        "description": "The evidence_key of a knowledge_search result.",
                    },
                    "window": {
                        "type": "integer",
                        "description": f"Neighbouring paragraphs on each side (0-{MAX_READ_WINDOW}).",
                        "default": 1,
                    },
                },
                "required": ["evidence_key"],
            },
        },
    },
}


def get_knowledge_evidence_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return {
        **copy.deepcopy(KNOWLEDGE_EVIDENCE_DEFINITIONS),
        **get_knowledge_episode_definitions(),
        **get_knowledge_source_update_definitions(),
        **get_knowledge_structured_definitions(),
    }
