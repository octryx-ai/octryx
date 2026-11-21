"""Whether a reporter's Teams reply may be posted as a Jira comment.

Posting the reply is an external write the reporter's answer triggers, not a user in a chat turn.
It never happens implicitly: the Workspace opts in with ``teams_reply_to_jira: true`` in its
config (default false), and even then a Workspace ``approval_policy`` rule covering
``add_jira_comment`` keeps it off, because an inbound reply has no turn that could wait for the
approval and re-run the call once it is granted.

Without the setting the answer still reaches the resumed agent session; a comment the agent then
decides to post runs through the normal tool dispatch, approval gate included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tool_approval_rules import tool_approval_requirement

TEAMS_REPLY_TO_JIRA_CONFIG_KEY = "teams_reply_to_jira"
JIRA_COMMENT_TOOL = "add_jira_comment"


@dataclass(frozen=True, slots=True)
class JiraReplyDecision:
    allowed: bool
    reason: str


def teams_reply_to_jira_decision(project_config: dict[str, Any] | None) -> JiraReplyDecision:
    """Allowed only under an explicit Workspace opt-in and no approval rule for the comment tool."""
    config = project_config if isinstance(project_config, dict) else {}
    if config.get(TEAMS_REPLY_TO_JIRA_CONFIG_KEY) is not True:
        return JiraReplyDecision(False, "teams_reply_to_jira_disabled")
    if tool_approval_requirement(JIRA_COMMENT_TOOL, config).required:
        return JiraReplyDecision(False, "approval_required")
    return JiraReplyDecision(True, "teams_reply_to_jira_enabled")


__all__ = [
    "JIRA_COMMENT_TOOL",
    "TEAMS_REPLY_TO_JIRA_CONFIG_KEY",
    "JiraReplyDecision",
    "teams_reply_to_jira_decision",
]
