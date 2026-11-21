"""Schemas of the Memory lobe tools.

Like the Knowledge evidence tools, neither schema has a scope, Workspace or user property: the
Workspace and the author come from the run. The bounds mirror ``services/knowledge/memory`` (a
definition module imports no service).
"""

from __future__ import annotations

import copy

MAX_MEMORY_TEXT_CHARS = 2000
MAX_RECALL_LIMIT = 20
MEMORY_CLASSES = ["personal", "decision", "convention", "learning", "episode_summary"]
# Answer feedback is written by the thumbs in the chat, never remembered by the agent, and recalled
# only when a recall names it.
RECALL_CLASSES = [*MEMORY_CLASSES, "answer_feedback"]


KNOWLEDGE_MEMORY_DEFINITIONS: dict[str, dict] = {
    "memory_remember": {
        "type": "function",
        "function": {
            "name": "memory_remember",
            "description": (
                "Remember something the user explicitly asked you to remember (a preference, a decision, a "
                "convention, a lesson), stated in the user's own words. Only use it when the user asks to "
                "remember something; never for content the user has not seen, and never for credentials or "
                "secrets (they are refused). Default scope is the user's personal memory. Use scope "
                "'workspace' only when the user says it is a team decision or convention; that needs the "
                "Workspace admin or owner role, otherwise the state is denied: tell the user and offer "
                "personal memory instead. state recorded, confirmed (a repetition confirmed an earlier "
                "memory) or already_known. Memory is not Knowledge evidence and is never cited as a source."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            f"The statement to remember, as the user said it (max {MAX_MEMORY_TEXT_CHARS} "
                            "characters), e.g. 'We use Java 21 for all services.'"
                        ),
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["user", "workspace"],
                        "description": "user (default): personal memory. workspace: team memory of this Workspace.",
                        "default": "user",
                    },
                    "class": {
                        "type": "string",
                        "enum": MEMORY_CLASSES,
                        "description": (
                            "personal (default for user scope; user scope only), decision or convention "
                            "(workspace scope only), learning (what worked or failed and why), or "
                            "episode_summary."
                        ),
                    },
                    "product": {
                        "type": "string",
                        "description": "Optional, workspace scope only: the product key it is about.",
                    },
                    "expires_in_days": {
                        "type": "integer",
                        "description": "Optional: forget it after this many days (1-3650), for temporary facts.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    "memory_recall": {
        "type": "function",
        "function": {
            "name": "memory_recall",
            "description": (
                "Recall memories from earlier sessions in this Workspace: the user's preferences and the "
                "team's decisions, conventions and learnings, matched by words (without query: the newest). "
                "Read-only. Memory is NOT source evidence: never cite it or link it; present each memory with "
                "its present_as wording and prefer Knowledge (knowledge_search) when they disagree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to look for. Optional."},
                    "classes": {
                        "type": "array",
                        "items": {"type": "string", "enum": RECALL_CLASSES},
                        "description": "Optional classes; answer_feedback comes back only when named.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum memories to return (1-{MAX_RECALL_LIMIT}).",
                        "default": 8,
                    },
                },
                "required": [],
            },
        },
    },
}


def get_knowledge_memory_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(KNOWLEDGE_MEMORY_DEFINITIONS)
