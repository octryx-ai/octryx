"""Schema of ``knowledge_episode_summary``: the agent saves the session's episode summary."""

from __future__ import annotations

MAX_EPISODE_CHARS = 8000


def get_knowledge_episode_definitions() -> dict[str, dict]:
    return {
        "knowledge_episode_summary": {
            "type": "function",
            "function": {
                "name": "knowledge_episode_summary",
                "description": (
                    "Save what this session established (questions, decisions, findings, outcomes and the "
                    "sources they rest on as markdown links) as the session's episode in the Workspace "
                    "Knowledge, where later sessions find it through knowledge_search, cited with a link to "
                    "this session. Use it when the user asks to save or summarize the session into Knowledge. "
                    "Write only what the session showed; never credentials, secrets or raw tool output "
                    "(secrets are redacted). Saving the same summary again changes nothing (state duplicate); "
                    "a changed summary replaces the session's previous one. state needs_configuration means "
                    "the Workspace does not accept session episodes; say so."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": f"The session summary in Markdown (max {MAX_EPISODE_CHARS} characters).",
                        },
                        "title": {"type": "string", "description": "Optional short title of the session."},
                        "products": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional product keys the session is about.",
                        },
                        "version": {"type": "string", "description": "Optional product version."},
                    },
                    "required": ["summary"],
                },
            },
        },
    }


__all__ = ["get_knowledge_episode_definitions"]
