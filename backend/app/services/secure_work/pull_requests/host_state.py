"""A pull request as its host reports it, mapped onto the recorded ``WorkPullRequest`` vocabulary.

Status (closed, explicit per host; an unmapped host state is :class:`HostStateError` ``unknown_host_state``, never
a guess):

- Bitbucket Server/Data Center: ``OPEN`` → ``open``, ``MERGED`` → ``merged``, ``DECLINED`` → ``declined``;
- Bitbucket Cloud: the same, plus ``SUPERSEDED`` → ``closed``;
- GitHub: ``open`` → ``open``; ``closed`` with ``merged``/``merged_at`` → ``merged``, else ``closed``.

Reviewers are ``{"username", "name", "approval", ["account_id"]}`` with ``approval`` one of ``approved``,
``needs_work`` (Bitbucket) / ``changes_requested`` (GitHub), ``commented``, ``pending``. ``approvals`` lists the
approving reviewers. Build status is aggregated over the head commit's statuses: ``failed`` (any failed),
``in_progress``, ``stopped``, ``successful`` (all succeeded); none reported is ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..jira_values import parse_datetime

STATUS_OPEN, STATUS_MERGED, STATUS_DECLINED, STATUS_CLOSED = "open", "merged", "declined", "closed"
BITBUCKET_SERVER_STATES = {"OPEN": STATUS_OPEN, "MERGED": STATUS_MERGED, "DECLINED": STATUS_DECLINED}
BITBUCKET_CLOUD_STATES = {**BITBUCKET_SERVER_STATES, "SUPERSEDED": STATUS_CLOSED}
APPROVED, NEEDS_WORK, CHANGES_REQUESTED, COMMENTED, PENDING = (
    "approved", "needs_work", "changes_requested", "commented", "pending")
_SERVER_APPROVAL = {"APPROVED": APPROVED, "NEEDS_WORK": NEEDS_WORK, "UNAPPROVED": PENDING}
_CLOUD_APPROVAL = {"approved": APPROVED, "changes_requested": NEEDS_WORK}
_GITHUB_REVIEW = {"APPROVED": APPROVED, "CHANGES_REQUESTED": CHANGES_REQUESTED, "COMMENTED": COMMENTED,
                  "DISMISSED": PENDING}
BUILD_FAILED, BUILD_IN_PROGRESS, BUILD_STOPPED, BUILD_SUCCESSFUL = "failed", "in_progress", "stopped", "successful"
_BUILD_STATES = {"FAILED": BUILD_FAILED, "ERROR": BUILD_FAILED, "FAILURE": BUILD_FAILED,
                 "INPROGRESS": BUILD_IN_PROGRESS, "IN_PROGRESS": BUILD_IN_PROGRESS, "PENDING": BUILD_IN_PROGRESS,
                 "STOPPED": BUILD_STOPPED, "CANCELLED": BUILD_STOPPED,
                 "SUCCESSFUL": BUILD_SUCCESSFUL, "SUCCESS": BUILD_SUCCESSFUL}


class HostStateError(Exception):
    """The host answered with something the mapping does not know; ``code`` names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class HostPullRequest:
    status: str
    title: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    url: str | None = None
    head_commit: str | None = None
    author: dict[str, Any] = field(default_factory=dict)
    reviewers: list[dict[str, Any]] = field(default_factory=list)
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    host_state: str = ""

    @property
    def approvals(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.reviewers if item.get("approval") == APPROVED]


def _mapped(states: dict[str, str], raw: Any, host: str) -> str:
    key = str(raw or "").strip().upper()
    if key not in states:
        raise HostStateError("unknown_host_state", f"{host} reported the pull request state {key or '(none)'!r}.")
    return states[key]


def _epoch_ms(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).replace(tzinfo=None)


def bitbucket_server_state(pr: dict[str, Any]) -> HostPullRequest:
    reviewers = []
    for item in pr.get("reviewers") or []:
        user = item.get("user") or {}
        status = str(item.get("status") or ("APPROVED" if item.get("approved") else "UNAPPROVED")).upper()
        reviewers.append({"username": user.get("name") or user.get("slug"), "name": user.get("displayName"),
                          "approval": _SERVER_APPROVAL.get(status, PENDING)})
    author = (pr.get("author") or {}).get("user") or {}
    from_ref, to_ref = pr.get("fromRef") or {}, pr.get("toRef") or {}
    return HostPullRequest(
        status=_mapped(BITBUCKET_SERVER_STATES, pr.get("state"), "Bitbucket"),
        title=pr.get("title"), source_branch=from_ref.get("displayId"), target_branch=to_ref.get("displayId"),
        url=str(((pr.get("links") or {}).get("self") or [{}])[0].get("href") or "") or None,
        head_commit=from_ref.get("latestCommit"),
        author={"username": author.get("name"), "name": author.get("displayName")} if author else {},
        reviewers=reviewers, source_created_at=_epoch_ms(pr.get("createdDate")),
        source_updated_at=_epoch_ms(pr.get("updatedDate")), host_state=str(pr.get("state") or ""),
    )


def bitbucket_cloud_state(pr: dict[str, Any]) -> HostPullRequest:
    reviewers = []
    for item in pr.get("participants") or []:
        if item.get("role") != "REVIEWER":
            continue
        user = item.get("user") or {}
        state = str(item.get("state") or "").lower()
        approval = APPROVED if item.get("approved") else _CLOUD_APPROVAL.get(state, PENDING)
        reviewers.append({"username": user.get("nickname") or user.get("account_id"), "name": user.get("display_name"),
                          "account_id": user.get("account_id"), "approval": approval})
    author = pr.get("author") or {}
    source, destination = pr.get("source") or {}, pr.get("destination") or {}
    return HostPullRequest(
        status=_mapped(BITBUCKET_CLOUD_STATES, pr.get("state"), "Bitbucket Cloud"),
        title=pr.get("title"), source_branch=(source.get("branch") or {}).get("name"),
        target_branch=(destination.get("branch") or {}).get("name"),
        url=str(((pr.get("links") or {}).get("html") or {}).get("href") or "") or None,
        head_commit=(source.get("commit") or {}).get("hash"),
        author={"username": author.get("nickname"), "name": author.get("display_name"),
                "account_id": author.get("account_id")} if author else {},
        reviewers=reviewers, source_created_at=parse_datetime(pr.get("created_on")),
        source_updated_at=parse_datetime(pr.get("updated_on")), host_state=str(pr.get("state") or ""),
    )


def github_state(pr: dict[str, Any], reviews: list[dict[str, Any]]) -> HostPullRequest:
    state = str(pr.get("state") or "").strip().lower()
    if state == "open":
        status = STATUS_OPEN
    elif state == "closed":
        status = STATUS_MERGED if (pr.get("merged") is True or pr.get("merged_at")) else STATUS_CLOSED
    else:
        raise HostStateError("unknown_host_state", f"GitHub reported the pull request state {state or '(none)'!r}.")
    latest: dict[str, str] = {}
    for review in reviews:  # GitHub lists reviews oldest first: the newest one per reviewer decides
        login = str((review.get("user") or {}).get("login") or "")
        if login and str(review.get("state") or "").upper() in _GITHUB_REVIEW:
            latest[login] = _GITHUB_REVIEW[str(review["state"]).upper()]
    requested = [str(item.get("login") or "") for item in pr.get("requested_reviewers") or []]
    reviewers = [{"username": login, "name": login,
                  "approval": PENDING if login in requested else latest.get(login, PENDING)}
                 for login in dict.fromkeys([*requested, *latest]) if login]
    user = pr.get("user") or {}
    return HostPullRequest(
        status=status, title=pr.get("title"), source_branch=(pr.get("head") or {}).get("ref"),
        target_branch=(pr.get("base") or {}).get("ref"), url=pr.get("html_url"),
        head_commit=(pr.get("head") or {}).get("sha"),
        author={"username": user.get("login"), "name": user.get("login")} if user else {},
        reviewers=reviewers, source_created_at=parse_datetime(pr.get("created_at")),
        source_updated_at=parse_datetime(pr.get("updated_at")), host_state=state,
    )


def aggregate_build_status(states: list[Any]) -> str | None:
    """One build status over the commit's reported statuses (``None`` when none reported)."""
    mapped = [_BUILD_STATES.get(str(item or "").strip().upper()) for item in states]
    if not mapped:
        return None
    for outcome in (BUILD_FAILED, BUILD_IN_PROGRESS, BUILD_STOPPED):
        if outcome in mapped:
            return outcome
    if all(item == BUILD_SUCCESSFUL for item in mapped):
        return BUILD_SUCCESSFUL
    raise HostStateError("unknown_build_state", "The host reported a build state the mapping does not know.")


__all__ = [
    "BITBUCKET_CLOUD_STATES", "BITBUCKET_SERVER_STATES", "HostPullRequest", "HostStateError", "STATUS_CLOSED",
    "STATUS_DECLINED", "STATUS_MERGED", "STATUS_OPEN", "aggregate_build_status", "bitbucket_cloud_state",
    "bitbucket_server_state", "github_state",
]
