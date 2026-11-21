"""Readers of the parts of a Bitbucket webhook payload: repository, pull request, commits, build, people."""

from __future__ import annotations

from typing import Any

from .secure_work.jira_values import blank_to_none, object_value


def _payload_repository(payload: dict[str, Any]) -> dict[str, Any]:
    repo = object_value(payload.get("repository") or payload.get("repo"))
    project = object_value(repo.get("project"))
    return _drop_empty(
        {
            "project_key": repo.get("project_key") or project.get("key"),
            "slug": repo.get("slug") or repo.get("name"),
            "name": repo.get("name") or repo.get("slug"),
            "url": _link(repo),
        }
    )


def _pull_request(payload: dict[str, Any]) -> dict[str, Any]:
    pr = object_value(payload.get("pullRequest") or payload.get("pull_request") or payload.get("pr"))
    from_ref = object_value(pr.get("fromRef") or pr.get("from_ref"))
    to_ref = object_value(pr.get("toRef") or pr.get("to_ref"))
    return _drop_empty(
        {
            "id": str(pr.get("id")) if pr.get("id") is not None else None,
            "title": pr.get("title"),
            "state": pr.get("state"),
            "url": _link(pr),
            "source_branch": from_ref.get("displayId") or _short_ref(from_ref.get("id")),
            "target_branch": to_ref.get("displayId") or _short_ref(to_ref.get("id")),
            "source_repository": _repository_from_ref(from_ref) if from_ref else {},
            "target_repository": _repository_from_ref(to_ref) if to_ref else {},
            "reviewers": _reviewers(pr),
        }
    )


def _repository_from_ref(ref: dict[str, Any]) -> dict[str, Any]:
    repo = object_value(ref.get("repository"))
    project = object_value(repo.get("project"))
    return _drop_empty(
        {
            "project_key": project.get("key") or repo.get("project_key"),
            "slug": repo.get("slug") or repo.get("name"),
            "name": repo.get("name") or repo.get("slug"),
            "url": _link(repo),
        }
    )


def _first_ref_change(payload: dict[str, Any]) -> dict[str, Any]:
    changes = payload.get("changes")
    if isinstance(changes, list) and changes:
        return object_value(changes[0])
    return object_value(payload.get("ref_change") or payload.get("change"))


def _commit(payload: dict[str, Any], *, ref_change: dict[str, Any]) -> dict[str, Any]:
    explicit = object_value(payload.get("commit") or payload.get("latest_commit"))
    commits = _commits(payload)
    if not explicit and commits:
        explicit = object_value(commits[0])
    return _drop_empty(
        {
            "hash": (
                explicit.get("hash")
                or explicit.get("id")
                or ref_change.get("toHash")
                or payload.get("commit_hash")
            ),
            "previous_hash": ref_change.get("fromHash") or payload.get("previous_commit_hash"),
            "message": explicit.get("message") or payload.get("message"),
            "author": _actor(explicit, fallback_keys=("author", "authorName", "author_email")),
            "url": _link(explicit),
        }
    )


def _commits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("commits")
    if not isinstance(raw, list):
        return []
    return [
        _drop_empty(
            {
                "hash": item.get("hash") or item.get("id"),
                "message": item.get("message"),
                "author": _actor(object_value(item), fallback_keys=("author", "authorName", "author_email")),
                "url": _link(object_value(item)),
            }
        )
        for item in [object_value(entry) for entry in raw[:20]]
    ]


def _comment(payload: dict[str, Any]) -> dict[str, Any]:
    comment = object_value(payload.get("comment"))
    anchor = object_value(comment.get("anchor"))
    return _drop_empty(
        {
            "id": str(comment.get("id")) if comment.get("id") is not None else None,
            "text": comment.get("text"),
            "state": comment.get("state"),
            "file_path": anchor.get("path"),
            "line": anchor.get("line"),
            "url": _link(comment),
        }
    )


def _reviewer(payload: dict[str, Any]) -> dict[str, Any]:
    participant = object_value(payload.get("participant") or payload.get("reviewer"))
    user = object_value(participant.get("user")) if participant else {}
    return _drop_empty(
        {
            "name": user.get("name") or participant.get("name"),
            "display_name": user.get("displayName") or participant.get("display_name"),
            "email": user.get("emailAddress") or participant.get("email"),
            "status": participant.get("status") or payload.get("reviewer_status"),
        }
    )


def _reviewers(pr: dict[str, Any]) -> list[dict[str, Any]]:
    raw = pr.get("reviewers")
    if not isinstance(raw, list):
        return []
    return [_reviewer({"reviewer": object_value(item)}) for item in raw[:20]]


def _build(payload: dict[str, Any]) -> dict[str, Any]:
    build = object_value(payload.get("build") or payload.get("build_status"))
    return _drop_empty(
        {
            "key": build.get("key") or payload.get("build_key"),
            "state": build.get("state") or payload.get("build_state"),
            "name": build.get("name") or payload.get("build_name"),
            "url": build.get("url") or _link(build),
            "commit_hash": build.get("commit_hash") or build.get("commitId") or payload.get("commit_hash"),
        }
    )


def _actor(payload: dict[str, Any], fallback_keys: tuple[str, ...] = ("actor", "user", "author")) -> str | None:
    for key in fallback_keys:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            value = (
                candidate.get("displayName")
                or candidate.get("display_name")
                or candidate.get("name")
                or candidate.get("emailAddress")
            )
        else:
            value = candidate
        if blank_to_none(value):
            return str(value)
    return None


def _link(value: dict[str, Any]) -> str | None:
    links = object_value(value.get("links"))
    self_link = links.get("self")
    if isinstance(self_link, list) and self_link:
        return blank_to_none(object_value(self_link[0]).get("href"))
    if isinstance(self_link, dict):
        return blank_to_none(self_link.get("href"))
    return blank_to_none(value.get("url") or value.get("link"))


def _short_ref(value: Any) -> str | None:
    text = blank_to_none(value)
    if not text:
        return None
    return str(text).removeprefix("refs/heads/")


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: current for key, current in value.items() if current not in (None, "", [], {})}
