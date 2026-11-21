"""Literal-parameter grammar of the request analysis.

``LIMIT_PATTERN`` reads a limit the user literally states ("top 5", "10 tickets"), a request
parameter, never an intent. There are no prompt keyword tables.
"""

from __future__ import annotations

import re

LIMIT_PATTERN = re.compile(
    r"\b(?:limit|max(?:imum)?|top|first|only)\s+(?P<value>\d+)\b|\b(?P<count>\d+)\s+(?:page|pages|ticket|tickets|issue|issues|result|results|repo|repos|repositories|repository|commit|commits)\b",
    re.IGNORECASE,
)
IMPLICIT_LIMIT_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "search_jira_tickets": ("limit",),
    "list_recent_bitbucket_commits": ("limit", "per_repo_limit"),
    "list_bitbucket_commits": ("limit",),
    "list_bitbucket_branches": ("limit",),
    "list_bitbucket_pull_requests": ("limit",),
    "list_confluence_pages": ("limit",),
    "search_confluence": ("limit",),
    "list_workspace_directory": ("limit",),
    "list_workspace_git_commits": ("limit",),
    "load_tool_artifact": ("max_items",),
}
GENERIC_READ_LIMIT_KEYS: tuple[str, ...] = (
    "limit",
    "per_page",
    "page_size",
    "count",
    "max_results",
    "max_jobs",
)
