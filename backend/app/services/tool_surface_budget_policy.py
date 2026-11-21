"""Provider tool-definition budgeting policy for agent-loop turns.

Single owner for the tool-surface budgeting heuristics. These constants are the
explicit default budgeting policy: when a provider caps the number of tool
definitions per request (or a coding surface needs a focused tool set), the
priority lists below decide which tools survive the cut. Model/runtime
selection itself lives in :mod:`app.services.model_selection_policy`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..tools.tool_names import CODING_CORE_TOOL_NAMES, CODING_PREFLIGHT_TOOL_NAMES, GENERAL_CORE_TOOL_NAMES, ToolName

# Default priority tiers for coding surfaces: preflight checks first, then the
# core coding tools, then the delivery (Jira/Bitbucket/PR) tools below.
_CODING_PREFLIGHT_TOOLS: frozenset[ToolName] = CODING_PREFLIGHT_TOOL_NAMES
_CODING_CORE_TOOL_NAMES: tuple[ToolName, ...] = CODING_CORE_TOOL_NAMES
_GENERAL_CORE_TOOL_NAMES: tuple[ToolName, ...] = GENERAL_CORE_TOOL_NAMES
# A non-coding turn offers the governed default surface; under a provider cap the
# workflow-selection meta tools and the governed Knowledge and Memory tools are seated first.
_GENERAL_GOVERNED_TOOL_NAMES: tuple[str, ...] = (
    "select_workflow",
    "instruction_get",
    "get_current_time",
    "knowledge_search",
    "knowledge_read",
    "knowledge_changes",
    "memory_recall",
    "memory_remember",
    "search_confluence",
    "get_confluence_page",
)
# Coding disciplines that make a surface a coding surface. ``planning`` is the discipline every
# other turn reports (``model_selection_policy.coding_discipline_for_role``), so it does not.
_CODING_DISCIPLINES = frozenset({"edit", "test-fix", "repo-intelligence", "review"})
# Default cap applied to any coding surface even when the provider has no
# explicit tool limit; keeps the coding tool surface focused.
_CODING_DEFAULT_TOOL_LIMIT = 96
# Delivery tools that must survive budgeting so a coding turn can still ship
# its result (ticket lookups, branch/PR creation, clarification).
_CODING_DELIVERY_TOOL_NAMES: tuple[str, ...] = (
    "get_jira_ticket",
    "search_jira_tickets",
    "list_jira_versions",
    "get_bitbucket_pull_request",
    "get_bitbucket_diff",
    "get_bitbucket_commit_changes",
    "create_bitbucket_branch",
    "create_bitbucket_pull_request",
    "commit_and_push_repository_branch",
    "add_jira_comment",
    "build_pull_request_description",
    "ask_clarification",
)
# Providers with hard limits on tool definitions per request.
_PROVIDER_TOOL_LIMITS: dict[str, int] = {
    "copilot": 96,
}


def tool_name_from_definition(definition: dict[str, Any]) -> str:
    return str(definition.get("function", {}).get("name") or "").strip()


def budget_tool_definitions_for_runtime(
    tool_definitions: list[dict[str, Any]],
    *,
    runtimes: list[dict[str, Any]],
    capability_type: str | None,
    coding_discipline: str | None,
    priority_tool_names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Trim tool definitions to the provider/surface budget, priority-first.

    ``priority_tool_names`` is a governed default set's declared order. When it is given and
    the surface exceeds the cap, the set's order decides the cut, then the remaining offered tools
    by name; catalog order never decides.
    """
    if not tool_definitions or not runtimes:
        return tool_definitions

    provider_name = str(runtimes[0].get("provider_name") or runtimes[0].get("provider") or "").strip().lower()
    tool_limit = _PROVIDER_TOOL_LIMITS.get(provider_name)
    normalized_capability = str(capability_type or "").strip().lower()
    normalized_discipline = str(coding_discipline or "").strip().lower()
    coding_surface = normalized_capability in {"change", "coding"} or normalized_discipline in _CODING_DISCIPLINES
    if coding_surface:
        tool_limit = tool_limit or _CODING_DEFAULT_TOOL_LIMIT
    if not tool_limit or len(tool_definitions) <= tool_limit:
        return tool_definitions

    by_name = {name: definition for definition in tool_definitions if (name := tool_name_from_definition(definition))}
    if priority_tool_names is not None:
        declared = [name for name in dict.fromkeys(priority_tool_names) if name in by_name]
        rest = sorted(set(by_name) - set(declared))
        return [by_name[name] for name in [*declared, *rest][:tool_limit]]
    prioritized: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _append_tool(name: str) -> None:
        if not name or name in seen_names:
            return
        definition = by_name.get(name)
        if not definition:
            return
        prioritized.append(definition)
        seen_names.add(name)

    priority_names: list[str] = []
    if coding_surface:
        priority_names.extend(sorted(_CODING_PREFLIGHT_TOOLS))
        priority_names.extend(_CODING_CORE_TOOL_NAMES)
        priority_names.extend(_CODING_DELIVERY_TOOL_NAMES)
    else:
        priority_names.extend(_GENERAL_GOVERNED_TOOL_NAMES)
        priority_names.extend(_GENERAL_CORE_TOOL_NAMES)

    for name in priority_names:
        _append_tool(name)

    for definition in tool_definitions:
        if len(prioritized) >= tool_limit:
            break
        tool_name = tool_name_from_definition(definition)
        if not tool_name or tool_name in seen_names:
            continue
        if coding_surface:
            # Default filter: once the priority tiers are seated, only
            # developer-facing tools may fill the remaining coding budget.
            is_developer_tool = (
                tool_name.startswith("code_")
                or tool_name.startswith("git_")
                or tool_name.startswith("run_")
                or tool_name.startswith("lsp_")
                or "workspace" in tool_name
                or "repository" in tool_name
                or "readme" in tool_name
                or tool_name
                in {
                    "ask_clarification",
                    "build_pull_request_description",
                    "commit_and_push_repository_branch",
                    "web_search",
                    "codesearch",
                    "spawn_sub_agent",
                    "get_context_from_subthreads",
                }
            )
            if not is_developer_tool:
                continue
        prioritized.append(definition)
        seen_names.add(tool_name)

    return prioritized[:tool_limit]


__all__ = [
    "tool_name_from_definition",
    "budget_tool_definitions_for_runtime",
]
