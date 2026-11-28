"""A pull request comment, from a webhook or from the sync's poll, in the one shape ``commands`` reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .events import _get, _header, _server_repo, _text


@dataclass(frozen=True, slots=True)
class CommentEvent:
    repository: str  # ``<provider>:<path>``
    pr_id: str
    comment_id: str
    author: str  # GitHub login, GitLab username, Bitbucket Server username, Bitbucket Cloud nickname
    body: str
    #: Bitbucket Cloud's Atlassian account id (how its people are linked); empty elsewhere.
    author_id: str = ""
    in_reply_to: str = ""  # the comment it answers ('' for a new one)
    inline: bool = False  # on a diff line (in a finding's thread)

    @property
    def provider(self) -> str:
        return self.repository.partition(":")[0]

    @property
    def thread_root(self) -> str:
        return self.in_reply_to or self.comment_id


def _make(provider: str, path: str, pr_id: str, comment_id: str, author: str, body: str,
          **facts: Any) -> CommentEvent | None:
    if not path or "/" not in path or not pr_id or not comment_id or not body:
        return None
    return CommentEvent(f"{provider}:{path}", pr_id, comment_id, author, body, **facts)


_GITLAB_THREAD_NOTES = frozenset({"DiffNote", "DiscussionNote"})


def _gitlab_note(payload: Any) -> CommentEvent | None:
    note = _get(payload, "object_attributes") or {}
    if (_text(payload, "object_kind") != "note" or _text(note, "noteable_type") != "MergeRequest"
            or _get(note, "system") is True or _text(note, "action") not in ("", "create")):
        return None
    thread = _text(note, "discussion_id") if _text(note, "type") in _GITLAB_THREAD_NOTES else ""
    return _make("gitlab", _text(payload, "project", "path_with_namespace"), _text(payload, "merge_request", "iid"),
                 _text(note, "id"), _text(payload, "user", "username"), _text(note, "note"), in_reply_to=thread,
                 inline=_text(note, "type") == "DiffNote")


def comment_event(payload: Any, headers: Mapping[str, str]) -> CommentEvent | None:
    github = _header(headers, "x-github-event")
    if github in ("issue_comment", "pull_request_review_comment"):
        if _text(payload, "action") != "created":
            return None
        comment = _get(payload, "comment") or {}
        if github == "issue_comment":
            if _get(payload, "issue", "pull_request") is None:
                return None  # a comment on an issue, not on a pull request
            number = _text(payload, "issue", "number")
        else:
            number = _text(payload, "pull_request", "number")
        return _make("github", _text(payload, "repository", "full_name"), number, _text(comment, "id"),
                     _text(comment, "user", "login"), _text(comment, "body"),
                     in_reply_to=_text(comment, "in_reply_to_id"), inline=github != "issue_comment")
    if _header(headers, "x-event-key") == "pullrequest:comment_created":
        comment = _get(payload, "comment") or {}
        return _make("bitbucket", _text(payload, "repository", "full_name"), _text(payload, "pullrequest", "id"),
                     _text(comment, "id"), _text(comment, "user", "nickname") or _text(comment, "user", "display_name"),
                     _text(comment, "content", "raw"), author_id=_text(comment, "user", "account_id"),
                     in_reply_to=_text(comment, "parent", "id"), inline=bool(_get(comment, "inline")))
    if _text(payload, "eventKey") == "pr:comment:added":
        comment = _get(payload, "comment") or {}
        pr = _get(payload, "pullRequest") or {}
        return _make("bitbucket", _server_repo(_get(pr, "toRef")), _text(pr, "id"), _text(comment, "id"),
                     _text(comment, "author", "name"), _text(comment, "text"),
                     in_reply_to=_text(payload, "commentParentId"))
    if _header(headers, "x-gitlab-event").lower() == "note hook":
        return _gitlab_note(payload)
    return None


def listed_comment(repository: str, item: Mapping[str, Any]) -> CommentEvent | None:
    provider, _, path = repository.partition(":")
    cloud_id = str(item.get("author_id") or "") if provider == "bitbucket" else ""
    return _make(provider, path, str(item.get("pr") or ""), str(item.get("id") or ""), str(item.get("author") or ""),
                 str(item.get("body") or ""), author_id=cloud_id, in_reply_to=str(item.get("in_reply_to") or ""),
                 inline=bool(item.get("inline")))


__all__ = ["CommentEvent", "comment_event", "listed_comment"]
