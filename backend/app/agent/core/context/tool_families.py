"""Named tool families a selected workflow's tool surface is built from.

One place for these lists, so the workflow tool surface (``turn_tool_surface``) and its callers
cannot drift apart. The Memory lobe joins the knowledge families as a read-only recall; recording
a memory is offered by the governed default surface of a user-facing chat turn, never inside a
workflow whose policy forbids mutating tools.
"""

from __future__ import annotations

COMMON_READ_ONLY_TOOLS = [
    "get_current_time",
    "get_system_context",
    "instruction_get",
    # Model-side workflow catalog: the selection meta tool must survive every
    # narrowed toolset so the model can enter a governed workflow.
    "select_workflow",
    "skill_search",
    "skill_get",
]

KNOWLEDGE_FORBIDDEN_TOOLS = ["skill_search", "skill_get"]

# Recall of what earlier sessions remember; never source evidence.
MEMORY_READ_TOOLS = ["memory_recall"]

# The governed Workspace evidence tools, plus memory recall beside them.
GOVERNED_KNOWLEDGE_TOOLS = ["knowledge_search", "knowledge_read", "knowledge_changes", *MEMORY_READ_TOOLS]

__all__ = [
    "COMMON_READ_ONLY_TOOLS",
    "GOVERNED_KNOWLEDGE_TOOLS",
    "KNOWLEDGE_FORBIDDEN_TOOLS",
    "MEMORY_READ_TOOLS",
]
