"""``get_github_commit_checks``: the CI results of one commit of an allowed GitHub repository (read only).

The PR review bot reads them for the commit it reviewed (``pr_review_bot.ci_results``): a red check is a finding, a
running one is named. GitHub has two kinds, both read page by page so none is missed:

- **commit statuses** (``GET /repos/{o}/{r}/commits/{sha}/statuses``, newest first): the latest state per
  ``context``: ``success`` / ``failure`` / ``error`` / ``pending``;
- **check runs** (``GET /repos/{o}/{r}/commits/{sha}/check-runs``): ``status`` ``queued`` / ``in_progress`` /
  ``completed`` with a ``conclusion`` (``success``, ``failure``, ``timed_out``, ``cancelled``, ``neutral``,
  ``skipped``, ``action_required``, ``stale``).

Every check is returned as ``{name, kind, state, url, description}`` with ``state`` one of ``success``, ``failure``,
``pending`` or ``other``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ...services.outbound_egress import CONNECTION_GITHUB
from ..context import ToolContext
from .common import _string, connection_http_json
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .github_source_control_common import require_github_repository_operation

_http_json = connection_http_json(CONNECTION_GITHUB)
PAGE = 100
_RED_CONCLUSIONS = frozenset({"failure", "timed_out", "action_required"})


async def _pages(context: ToolContext, url: str, key: str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = await _http_json("GET", url, headers=await _github_headers(context),
                                  params={"per_page": PAGE, "page": page})
        batch = (answer or {}).get(key) if key else answer
        batch = [item for item in batch or [] if isinstance(item, dict)]
        items.extend(batch)
        if len(batch) < PAGE:
            return items
        page += 1


def _status_state(state: str) -> str:
    return {"success": "success", "failure": "failure", "error": "failure", "pending": "pending"}.get(state, "other")


def _check_state(run: dict[str, Any]) -> str:
    if run.get("status") != "completed":
        return "pending"
    conclusion = str(run.get("conclusion") or "")
    return "success" if conclusion == "success" else "failure" if conclusion in _RED_CONCLUSIONS else "other"


class GetGitHubCommitChecksTool:
    name = "get_github_commit_checks"
    description = "CI results (commit statuses and check runs) of one commit of an allowed GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        commit = _string(params.get("commit"))
        if not owner or not repo or not commit:
            return {"error": "repository and commit are required and repository must be allowed"}
        if denied := await require_github_repository_operation(context, owner=owner, repo=repo, operation="read"):
            return denied
        base = f"{_github_base_url(context)}/repos/{owner}/{repo}/commits/{quote(commit, safe='')}"
        checks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for status in await _pages(context, f"{base}/statuses", None):  # newest first: the latest per context
            name = _string(status.get("context"))
            if name and name not in seen:
                seen.add(name)
                checks.append({"name": name, "kind": "status", "state": _status_state(_string(status.get("state"))),
                               "url": _string(status.get("target_url")),
                               "description": _string(status.get("description"))})
        statuses, refused = len(checks), ""
        try:
            runs = await _pages(context, f"{base}/check-runs", "check_runs")
        except httpx.HTTPStatusError as error:
            # A fine-grained personal access token gets 403 on check runs (only a
            # GitHub App reads them); the commit statuses were read and still count.
            if error.response.status_code not in (403, 404):
                raise
            runs, refused = [], f"check runs not readable with this token (GitHub App needed); " \
                               f"commit statuses read: {statuses}"
        for run in runs:
            checks.append({"name": _string(run.get("name")), "kind": "check_run", "state": _check_state(run),
                           "url": _string(run.get("html_url")),
                           "description": _string((run.get("output") or {}).get("title"))})
        return {"repository": f"{owner}/{repo}", "commit": commit, "checks": checks,
                **({"check_runs_unread": refused} if refused else {})}


__all__ = ["GetGitHubCommitChecksTool"]
