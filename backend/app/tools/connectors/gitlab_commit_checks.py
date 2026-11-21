"""``get_gitlab_commit_checks``: the CI results of one commit of an allowed GitLab project (read only).

The PR review bot reads them for the commit it reviewed (``pr_review_bot.ci_results``): a red check is a finding, a
running one is named. On GitLab every pipeline job is a commit status, and so is every external status (another
CI, another bot): ``GET /projects/:id/repository/commits/:sha/statuses`` lists the latest one per name, page by
page. ``status``: ``success``; ``failed`` (red unless the job is ``allow_failure``); ``created`` / ``pending`` /
``running`` / ``preparing`` / ``waiting_for_resource`` / ``scheduled`` (still running); ``canceled`` /
``skipped`` / ``manual`` (neither).

Every check is returned as ``{name, kind, state, url, description}`` with ``state`` one of ``success``, ``failure``,
``pending`` or ``other``, the shape of ``get_github_commit_checks``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITLAB
from ..context import ToolContext
from .common import _string, connection_http_json
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project
from .gitlab_mr_comments import pages
from .gitlab_source_control_common import require_gitlab_repository_operation

_http_json = connection_http_json(CONNECTION_GITLAB)
_RUNNING = frozenset({"created", "pending", "running", "preparing", "waiting_for_resource", "scheduled"})


def _state(status: dict[str, Any]) -> str:
    value = _string(status.get("status")).lower()
    if value == "success":
        return "success"
    if value == "failed":
        return "other" if status.get("allow_failure") is True else "failure"
    return "pending" if value in _RUNNING else "other"


class GetGitLabCommitChecksTool:
    name = "get_gitlab_commit_checks"
    description = "CI results (pipeline jobs and external commit statuses) of one commit of an allowed GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        commit = _string(params.get("commit"))
        if not project or not commit:
            return {"error": "project and commit are required and project must be allowed"}
        if denied := await require_gitlab_repository_operation(context, project=project, operation="read"):
            return denied
        url = (f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/repository/commits/"
               f"{quote(commit, safe='')}/statuses")
        checks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for status in await pages(_http_json, await _gitlab_headers(context), url, {}):
            name = _string(status.get("name"))
            if name and name not in seen:  # one per name (the latest; GitLab lists only those by default)
                seen.add(name)
                checks.append({"name": name, "kind": "job" if status.get("stage") else "status",
                               "state": _state(status), "url": _string(status.get("target_url")),
                               "description": _string(status.get("description"))})
        return {"project": project, "commit": commit, "checks": checks}


__all__ = ["GetGitLabCommitChecksTool"]
