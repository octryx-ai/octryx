"""Schema of the live Jira release status tool.

No scope property: the Workspace comes from the run's server-side ``ToolContext``, and the Jira
project from the Workspace connector's explicit product mapping. Merged into
``get_jira_definitions``, so it is a ``jira`` connector tool: visible only where the Workspace
activates Jira, with read risk (it is not in the mutating set) and audited as a connector call.
"""

from __future__ import annotations


def get_jira_release_definitions() -> dict[str, dict]:
    return {
        "jira_release_status": {
            "type": "function",
            "function": {
                "name": "jira_release_status",
                "description": (
                    "Query Jira live for the current status of one release of a product (a product key and a "
                    "version): whether it is released, its release date, the number of its issues per status "
                    "category (to do, in progress, done) and its open blockers, each with its Jira link. Read-only; "
                    "the Workspace and its Jira connection are the session's. Use it for 'what is the status of' "
                    "questions, never answer status from knowledge. For 'what changes in' a version use "
                    "knowledge_changes or knowledge_search instead. state needs_configuration means the "
                    "product has no Jira release mapping; say so. Cite version_url and each blocker's url as "
                    "markdown links and say the answer is as of queried_at."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string", "description": "Product key, as configured for the Workspace."},
                        "version": {"type": "string", "description": "The release version."},
                    },
                    "required": ["product", "version"],
                },
            },
        },
    }


__all__ = ["get_jira_release_definitions"]
