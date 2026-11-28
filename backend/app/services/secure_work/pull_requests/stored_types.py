"""The pull request fields a host refresh writes onto a ``WorkPullRequest`` row: status, reviewers, author, build."""

from typing import Literal, NotRequired, TypedDict

PullRequestStatus = Literal["open", "merged", "declined", "closed"]
ReviewerApproval = Literal["approved", "needs_work", "changes_requested", "commented", "pending"]
BuildStatus = Literal["failed", "in_progress", "stopped", "successful"]


class HostReviewer(TypedDict):
    username: str | None
    name: str | None
    approval: ReviewerApproval
    account_id: NotRequired[str | None]  # Bitbucket Cloud only


class HostAuthor(TypedDict):
    username: str | None
    name: str | None
    account_id: NotRequired[str | None]  # Bitbucket Cloud only


class NoHostAuthor(TypedDict):
    pass


__all__ = ["BuildStatus", "HostAuthor", "HostReviewer", "NoHostAuthor", "PullRequestStatus", "ReviewerApproval"]
