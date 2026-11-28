"""Whether a reporter's Teams reply may be posted as a Jira comment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tool_approval.rules import tool_approval_requirement

TEAMS_REPLY_TO_JIRA_CONFIG_KEY = "teams_reply_to_jira"
JIRA_COMMENT_TOOL = "add_jira_comment"


@dataclass(frozen=True, slots=True)
class JiraReplyDecision:
    allowed: bool
    reason: str


def teams_reply_to_jira_decision(project_config: dict[str, Any] | None) -> JiraReplyDecision:
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
