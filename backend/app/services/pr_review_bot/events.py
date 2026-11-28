"""A pull request webhook read into the one shape the review bot starts from."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

_GITHUB_ACTIONS = frozenset({"opened", "reopened", "synchronize", "ready_for_review"})
_CLOUD_KEYS = frozenset({"pullrequest:created", "pullrequest:updated"})
_SERVER_KEYS = frozenset({"pr:opened", "pr:from_ref_updated"})
_GITLAB_HOOK, _GITLAB_ACTIONS = "merge request hook", frozenset({"open", "reopen"})


@dataclass(frozen=True, slots=True)
class PullRequestEvent:
    repository: str  # ``<provider>:<path>``
    pr_id: str
    head_sha: str
    source_branch: str
    target_branch: str
    title: str = ""
    author: str = ""
    url: str = ""
    draft: bool = False
    #: The source branch lives in another repository (a fork): the bot cannot check it out by branch name.
    fork: bool = False
    #: Bitbucket Cloud's author as Atlassian account id (its ``author`` is a display name); empty elsewhere, where
    #: ``author`` is the login (GitHub) or username (Server/Data Center). Whose seat reviews (``seat_choice``).
    author_id: str = ""

    @property
    def provider(self) -> str:
        return self.repository.partition(":")[0]

    def as_context(self) -> dict[str, Any]:
        return asdict(self)


def _get(data: Any, *path: str) -> Any:
    for key in path:
        data = data.get(key) if isinstance(data, Mapping) else None
    return data


def _text(data: Any, *path: str) -> str:
    value = _get(data, *path)
    return "" if value is None else str(value).strip()


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((str(value) for key, value in headers.items() if key.lower() == name), "")


def _github(payload: Any) -> PullRequestEvent | None:
    if _text(payload, "action") not in _GITHUB_ACTIONS:
        return None
    pr = _get(payload, "pull_request") or {}
    base_repo, head_repo = _text(pr, "base", "repo", "full_name"), _text(pr, "head", "repo", "full_name")
    repository = base_repo or _text(payload, "repository", "full_name")
    return _event("github", repository, _text(pr, "number"), _text(pr, "head", "sha"), _text(pr, "head", "ref"),
                  _text(pr, "base", "ref"), title=_text(pr, "title"), author=_text(pr, "user", "login"),
                  url=_text(pr, "html_url"), draft=bool(_get(pr, "draft")),
                  fork=bool(head_repo) and head_repo.lower() != repository.lower())


def _cloud(payload: Any) -> PullRequestEvent | None:
    pr = _get(payload, "pullrequest") or {}
    repository = _text(pr, "destination", "repository", "full_name") or _text(payload, "repository", "full_name")
    source_repo = _text(pr, "source", "repository", "full_name")
    return _event("bitbucket", repository, _text(pr, "id"), _text(pr, "source", "commit", "hash"),
                  _text(pr, "source", "branch", "name"), _text(pr, "destination", "branch", "name"),
                  title=_text(pr, "title"), author=_text(pr, "author", "display_name"),
                  author_id=_text(pr, "author", "account_id"),
                  url=_text(pr, "links", "html", "href"), draft=bool(_get(pr, "draft")),
                  fork=bool(source_repo) and source_repo.lower() != repository.lower())


def _server_repo(ref: Any) -> str:
    project, slug = _text(ref, "repository", "project", "key"), _text(ref, "repository", "slug")
    return f"{project}/{slug}" if project and slug else ""


def _server(payload: Any) -> PullRequestEvent | None:
    pr = _get(payload, "pullRequest") or {}
    repository, source_repo = _server_repo(_get(pr, "toRef")), _server_repo(_get(pr, "fromRef"))
    links = _get(pr, "links", "self")
    url = _text(links[0], "href") if isinstance(links, list) and links else ""
    return _event("bitbucket", repository, _text(pr, "id"), _text(pr, "fromRef", "latestCommit"),
                  _text(pr, "fromRef", "displayId"), _text(pr, "toRef", "displayId"), title=_text(pr, "title"),
                  author=_text(pr, "author", "user", "name"), url=url, draft=bool(_get(pr, "draft")),
                  fork=bool(source_repo) and source_repo.lower() != repository.lower())


def _gitlab_ready(attributes: Any, changes: Any) -> bool:
    if _text(attributes, "oldrev"):
        return True
    return any(_get(changes, key, "previous") is True and _get(changes, key, "current") is False
               for key in ("draft", "work_in_progress"))


def _gitlab(payload: Any) -> PullRequestEvent | None:
    attributes = _get(payload, "object_attributes") or {}
    action = _text(attributes, "action")
    pushed = action == "update" and _gitlab_ready(attributes, _get(payload, "changes"))
    if action not in _GITLAB_ACTIONS and not pushed:
        return None
    repository = _text(attributes, "target", "path_with_namespace") or _text(payload, "project", "path_with_namespace")
    source, target = _text(attributes, "source_project_id"), _text(attributes, "target_project_id")
    return _event("gitlab", repository, _text(attributes, "iid"), _text(attributes, "last_commit", "id"),
                  _text(attributes, "source_branch"), _text(attributes, "target_branch"),
                  title=_text(attributes, "title"), author=_text(payload, "user", "username"),
                  url=_text(attributes, "url"),
                  draft=bool(_get(attributes, "draft") or _get(attributes, "work_in_progress")),
                  fork=bool(source) and bool(target) and source != target)


def _event(provider: str, path: str, pr_id: str, sha: str, source: str, target: str,
           **facts: Any) -> PullRequestEvent | None:
    if not path or "/" not in path or not pr_id or not source:
        return None
    return PullRequestEvent(f"{provider}:{path}", pr_id, sha, source, target, **facts)


def pull_request_event(payload: Any, headers: Mapping[str, str]) -> PullRequestEvent | None:
    if _header(headers, "x-github-event") == "pull_request":
        return _github(payload)
    if _header(headers, "x-event-key") in _CLOUD_KEYS:
        return _cloud(payload)
    if _text(payload, "eventKey") in _SERVER_KEYS:
        return _server(payload)
    if _header(headers, "x-gitlab-event").lower() == _GITLAB_HOOK and _text(payload, "object_kind") == "merge_request":
        return _gitlab(payload)
    return None


__all__ = ["PullRequestEvent", "pull_request_event"]
