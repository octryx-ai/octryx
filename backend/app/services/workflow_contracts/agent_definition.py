"""The synthetic agent definition (steps, tools, budgets) a coding workflow contract runs under."""

from __future__ import annotations

# Unknown providers resolve to NO delivery step (deny-by-default), never to a guessed toolset.
SOURCE_CONTROL_DELIVERY_TOOLS: dict[str, tuple[str, ...]] = {
    "bitbucket": ("commit_and_push_repository_branch", "create_bitbucket_pull_request"),
}
TICKET_DELIVERY_TOOLS: dict[str, tuple[str, ...]] = {
    "jira": ("add_jira_comment",),
}
# The phase toolset and step allowedTools intersect, so this union must cover every resolvable delivery tool.
ALL_CODING_DELIVERY_TOOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        tool
        for tools in (*SOURCE_CONTROL_DELIVERY_TOOLS.values(), *TICKET_DELIVERY_TOOLS.values())
        for tool in tools
    )
)


# 32 came from live evidence (a 44-block cleanup died at 20 while converging); 8 bounds the mechanical hand-off.
CODING_STEP_ITERATIONS = 20
CODING_CONTRACT_STEP_ITERATIONS = 32
CODING_DELIVERY_STEP_ITERATIONS = 8


