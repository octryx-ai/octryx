"""External events a watching run waits for, read into one closed shape."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

PR_APPROVED, PR_MERGED, PR_DECLINED = "pr.approved", "pr.merged", "pr.declined"
CI_SUCCEEDED, CI_FAILED = "ci.succeeded", "ci.failed"
JIRA_STATUS = "jira.status"
# Bitbucket Cloud names its event in the ``X-Event-Key`` header (Server/Data Center: ``eventKey`` in the body).
_CLOUD_PR = {"pullrequest:fulfilled": PR_MERGED, "pullrequest:rejected": PR_DECLINED,
             "pullrequest:approved": PR_APPROVED}
APPROVAL_DECIDED = "approval.decided"


@dataclass(frozen=True, slots=True)
class WatchEvent:
    condition: str
    provider: str = ""
    repository: str = ""
    pr_id: str = ""
    branch: str = ""
    job: str = ""
    ticket_key: str = ""
    work_state: str = ""
    approval_id: str = ""
    sha: str = ""
    workflow: str = ""
    build_number: str = ""
    reverts: str = ""
    pr_url: str = ""  # the pull request's web URL in the signed payload: its host binds the event (``watch.matches``)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value}


def _get(data: Any, *path: str) -> Any:
    for key in path:
        data = data.get(key) if isinstance(data, Mapping) else None
    return data


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((str(value) for key, value in headers.items() if key.lower() == name), "")


# How the providers' revert buttons describe what they revert: GitHub "Reverts owner/repo#12" and branch
# "revert-12-<branch>", GitLab "This reverts merge request !12", Bitbucket branch "revert-pr-12".
_REVERTS = (re.compile(r"\bReverts [\w.-]+/[\w.-]+#(\d+)"), re.compile(r"\breverts merge request !(\d+)", re.I))
_REVERT_BRANCH = re.compile(r"^revert-(?:pr-)?(\d+)(?:-|$)")


def reverted_id(title: Any, body: Any, branch: Any) -> str:
    for pattern in _REVERTS:
        if found := pattern.search(str(body or "")):
            return found.group(1)
    if str(title or "").startswith("Revert ") and (found := _REVERT_BRANCH.match(str(branch or ""))):
        return found.group(1)
    return ""


def scm_event(payload: Any, headers: Mapping[str, str]) -> WatchEvent | None:
    github_event = _header(headers, "x-github-event")
    if github_event in ("pull_request", "pull_request_review"):
        repository = str(_get(payload, "repository", "full_name") or "")
        number = str(_get(payload, "pull_request", "number") or "")
        url = str(_get(payload, "pull_request", "html_url") or "")
        if github_event == "pull_request_review":
            state = str(_get(payload, "review", "state") or "").lower()
            return WatchEvent(PR_APPROVED, "github", repository, number, pr_url=url) if state == "approved" else None
        if _get(payload, "action") == "closed":
            merged = bool(_get(payload, "pull_request", "merged"))
            reverts = reverted_id(_get(payload, "pull_request", "title"), _get(payload, "pull_request", "body"),
                                  _get(payload, "pull_request", "head", "ref")) if merged else ""
            return WatchEvent(PR_MERGED if merged else PR_DECLINED, "github", repository, number, reverts=reverts,
                              pr_url=url)
        return None
    if _get(payload, "object_kind") == "merge_request":
        action = str(_get(payload, "object_attributes", "action") or "")
        condition = {"merge": PR_MERGED, "close": PR_DECLINED, "approved": PR_APPROVED}.get(action)
        if condition is None:
            return None
        attributes = _get(payload, "object_attributes") or {}
        reverts = reverted_id(_get(attributes, "title"), _get(attributes, "description"),
                              _get(attributes, "source_branch")) if condition == PR_MERGED else ""
        return WatchEvent(condition, "gitlab", str(_get(payload, "project", "path_with_namespace") or ""),
                          str(_get(payload, "object_attributes", "iid") or ""), reverts=reverts,
                          pr_url=str(_get(attributes, "url") or ""))
    cloud_event = _header(headers, "x-event-key")
    if cloud_event.startswith("pullrequest:"):
        condition = _CLOUD_PR.get(cloud_event)
        if condition is None:
            return None
        pull = _get(payload, "pullrequest") or {}
        reverts = reverted_id(_get(pull, "title"), _get(pull, "description"),
                              _get(pull, "source", "branch", "name")) if condition == PR_MERGED else ""
        return WatchEvent(condition, "bitbucket", str(_get(payload, "repository", "full_name") or ""),
                          str(_get(payload, "pullrequest", "id") or ""), reverts=reverts,
                          pr_url=str(_get(pull, "links", "html", "href") or ""))
    event_key = str(_get(payload, "eventKey") or "")
    condition = {"pr:merged": PR_MERGED, "pr:declined": PR_DECLINED, "pr:reviewer:approved": PR_APPROVED}.get(
        event_key)
    if condition is None:
        return None
    repo = _get(payload, "pullRequest", "toRef", "repository") or {}
    path = f"{_get(repo, 'project', 'key') or ''}/{_get(repo, 'slug') or ''}"
    pull = _get(payload, "pullRequest") or {}
    reverts = reverted_id(_get(pull, "title"), _get(pull, "description"),
                          _get(pull, "fromRef", "displayId")) if condition == PR_MERGED else ""
    links = _get(pull, "links", "self")
    url = _get(links[0], "href") if isinstance(links, list) and links else ""
    return WatchEvent(condition, "bitbucket", path, str(_get(payload, "pullRequest", "id") or ""), reverts=reverts,
                      pr_url=str(url or ""))


def ci_event(payload: Any, headers: Mapping[str, str]) -> WatchEvent | None:
    if _header(headers, "x-event-key") in ("repo:commit_status_created", "repo:commit_status_updated"):
        state = str(_get(payload, "commit_status", "state") or "").upper()
        if state not in ("SUCCESSFUL", "FAILED", "STOPPED"):
            return None
        return WatchEvent(CI_SUCCEEDED if state == "SUCCESSFUL" else CI_FAILED, "bitbucket",
                          str(_get(payload, "repository", "full_name") or ""),
                          branch=str(_get(payload, "commit_status", "refname") or ""),
                          sha=str(_get(payload, "commit_status", "commit", "hash") or ""))
    if _header(headers, "x-github-event") == "workflow_run":
        if _get(payload, "action") != "completed":
            return None
        conclusion = str(_get(payload, "workflow_run", "conclusion") or "")
        return WatchEvent(CI_SUCCEEDED if conclusion == "success" else CI_FAILED, "github",
                          str(_get(payload, "repository", "full_name") or ""),
                          branch=str(_get(payload, "workflow_run", "head_branch") or ""),
                          sha=str(_get(payload, "workflow_run", "head_sha") or ""),
                          workflow=str(_get(payload, "workflow_run", "name") or ""))
    if _get(payload, "object_kind") == "pipeline":
        status = str(_get(payload, "object_attributes", "status") or "")
        if status not in ("success", "failed", "canceled"):
            return None
        return WatchEvent(CI_SUCCEEDED if status == "success" else CI_FAILED, "gitlab",
                          str(_get(payload, "project", "path_with_namespace") or ""),
                          branch=str(_get(payload, "object_attributes", "ref") or ""),
                          sha=str(_get(payload, "object_attributes", "sha") or ""))
    build = _get(payload, "build")
    if isinstance(build, Mapping) and _get(payload, "name"):
        if str(build.get("phase") or "").upper() not in ("COMPLETED", "FINALIZED"):
            return None
        status = str(build.get("status") or "").upper()
        return WatchEvent(CI_SUCCEEDED if status == "SUCCESS" else CI_FAILED, "jenkins", job=str(payload["name"]),
                          sha=str(_get(build, "scm", "commit") or ""),
                          build_number=str(build.get("number") or ""))
    return None


__all__ = ["APPROVAL_DECIDED", "CI_FAILED", "CI_SUCCEEDED", "JIRA_STATUS", "PR_APPROVED", "PR_DECLINED",
           "PR_MERGED", "WatchEvent", "ci_event", "reverted_id", "scm_event"]
