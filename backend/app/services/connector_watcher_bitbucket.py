from __future__ import annotations

import re
from typing import Any

from .connector_watcher_bitbucket_payload import (
    _actor,
    _build,
    _comment,
    _commit,
    _commits,
    _drop_empty,
    _first_ref_change,
    _payload_repository,
    _pull_request,
    _reviewer,
    _short_ref,
)
from .secure_work.jira_values import blank_to_none, parse_datetime

JIRA_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
ZERO_HASHES = {
    "0000000000000000000000000000000000000000",
    "00000000000000000000000000000000000000000000",
}


def normalize_bitbucket_event(payload: dict[str, Any], *, watcher_scope: dict[str, Any]) -> dict[str, Any]:
    event_key = str(payload.get("eventKey") or payload.get("event_key") or payload.get("event_type") or "").strip()
    repository = _payload_repository(payload)
    pull_request = _pull_request(payload)
    ref_change = _first_ref_change(payload)
    commit = _commit(payload, ref_change=ref_change)
    build = _build(payload)
    comment = _comment(payload)
    reviewer = _reviewer(payload)
    actor = _actor(payload)
    action = _action(event_key, payload, pull_request=pull_request, ref_change=ref_change, build=build)
    event_type = f"bitbucket.{action}"
    branch = _branch(payload, pull_request=pull_request, ref_change=ref_change)
    force_push = _is_force_push(payload, ref_change=ref_change, action=action)
    external_id = _external_id(
        payload,
        action=action,
        pull_request=pull_request,
        branch=branch,
        commit=commit,
        build=build,
    )
    occurred_at = parse_datetime(payload.get("occurred_at") or payload.get("date") or payload.get("timestamp"))
    work_item_keys = _work_item_keys(payload, pull_request=pull_request, branch=branch, commit=commit, comment=comment)
    scope = _event_scope(
        watcher_scope,
        repository=repository,
        branch=branch,
        pull_request=pull_request,
        work_item_keys=work_item_keys,
    )
    normalized = _drop_empty(
        {
            "bitbucket_action": action,
            "repository": repository,
            "branch": branch,
            "target_branch": pull_request.get("target_branch"),
            "pull_request": pull_request,
            "commit": commit,
            "commits": _commits(payload),
            "comment": comment,
            "reviewer": reviewer,
            "build": build,
            "force_push": force_push,
            "work_item_keys": work_item_keys,
            "requires_replan": _requires_replan(payload, force_push=force_push, branch=branch, action=action),
            "human_actor": _human_actor(payload, actor),
        }
    )
    return {
        "event_type": event_type,
        "external_id": external_id,
        "actor": actor,
        "occurred_at": occurred_at,
        "scope": scope,
        "normalized": normalized,
    }


def _action(
    event_key: str,
    payload: dict[str, Any],
    *,
    pull_request: dict[str, Any],
    ref_change: dict[str, Any],
    build: dict[str, Any],
) -> str:
    explicit = blank_to_none(payload.get("bitbucket_action") or payload.get("action"))
    if explicit:
        return str(explicit).replace(":", ".").replace("_", ".").lower()
    if event_key == "repo:refs_changed" and ref_change:
        change_type = str(ref_change.get("type") or "").upper()
        ref_id = str(ref_change.get("refId") or "")
        from_hash = str(ref_change.get("fromHash") or "")
        to_hash = str(ref_change.get("toHash") or "")
        if ref_id.startswith("refs/heads/") and from_hash in ZERO_HASHES:
            return "branch.created"
        if ref_id.startswith("refs/heads/") and to_hash in ZERO_HASHES:
            return "branch.deleted"
        if payload.get("force_push") or payload.get("forced") or ref_change.get("forced") or "FORCE" in change_type:
            return "commit.force_pushed"
        return "commit.pushed"
    mapped = {
        "pr:opened": "pull_request.opened",
        "pr:from_ref_updated": "pull_request.updated",
        "pr:modified": "pull_request.updated",
        "pr:reviewer:approved": "pull_request.approved",
        "pr:reviewer:unapproved": "pull_request.changes_requested",
        "pr:reviewer:needs_work": "pull_request.changes_requested",
        "pr:comment:added": "pull_request.comment_added",
        "pr:comment:edited": "pull_request.comment_updated",
        "pr:comment:deleted": "pull_request.comment_deleted",
        "pr:comment:resolved": "pull_request.comment_resolved",
        "pr:merged": "pull_request.merged",
        "pr:declined": "pull_request.declined",
        "repo:refs_changed": "commit.pushed",
        "repo:modified": "repository.updated",
        "diagnostics:build_status": "build.status_changed",
    }
    if event_key in mapped:
        return mapped[event_key]
    if build:
        return "build.status_changed"
    if pull_request:
        return "pull_request.updated"
    if ref_change:
        return "commit.pushed"
    return "event.received"


def _event_scope(
    watcher_scope: dict[str, Any],
    *,
    repository: dict[str, Any],
    branch: str | None,
    pull_request: dict[str, Any],
    work_item_keys: list[str],
) -> dict[str, Any]:
    return {
        **watcher_scope,
        **_drop_empty(
            {
                "bitbucket_project_key": repository.get("project_key"),
                "repository_slug": repository.get("slug"),
                "repository_name": repository.get("name"),
                "branch": branch,
                "target_branch": pull_request.get("target_branch"),
                "pull_request_id": pull_request.get("id"),
                "pull_request_url": pull_request.get("url"),
                "work_item_keys": work_item_keys,
            }
        ),
    }


def _branch(payload: dict[str, Any], *, pull_request: dict[str, Any], ref_change: dict[str, Any]) -> str | None:
    return blank_to_none(
        payload.get("branch")
        or pull_request.get("source_branch")
        or _short_ref(ref_change.get("refId") or ref_change.get("ref_id"))
    )


def _external_id(
    payload: dict[str, Any],
    *,
    action: str,
    pull_request: dict[str, Any],
    branch: str | None,
    commit: dict[str, Any],
    build: dict[str, Any],
) -> str | None:
    explicit = blank_to_none(payload.get("external_id") or payload.get("event_id") or payload.get("id"))
    if explicit:
        return explicit
    if pull_request.get("id"):
        return f"pr:{pull_request['id']}:{action}"
    if build.get("key") or build.get("commit_hash"):
        return f"build:{build.get('key') or build.get('commit_hash')}:{action}"
    if commit.get("hash"):
        return f"commit:{commit['hash']}:{action}"
    if branch:
        return f"branch:{branch}:{action}"
    return None


def _is_force_push(payload: dict[str, Any], *, ref_change: dict[str, Any], action: str) -> bool:
    change_type = str(ref_change.get("type") or "").upper()
    return bool(
        payload.get("force_push")
        or payload.get("forced")
        or ref_change.get("forced")
        or "FORCE" in change_type
        or action == "commit.force_pushed"
    )


def _requires_replan(payload: dict[str, Any], *, force_push: bool, branch: str | None, action: str) -> bool:
    if payload.get("requires_replan") is not None:
        return bool(payload.get("requires_replan"))
    replan_actions = {
        "commit.pushed",
        "commit.force_pushed",
        "pull_request.updated",
        "branch.created",
        "branch.deleted",
    }
    return bool(branch and action in replan_actions and (force_push or _human_actor(payload, _actor(payload))))


def _human_actor(payload: dict[str, Any], actor: str | None) -> bool:
    if payload.get("human_actor") is not None:
        return bool(payload.get("human_actor"))
    lowered = (actor or "").lower()
    return bool(actor and "bot" not in lowered and "ci" not in lowered and "service" not in lowered)


def _work_item_keys(
    payload: dict[str, Any],
    *,
    pull_request: dict[str, Any],
    branch: str | None,
    commit: dict[str, Any],
    comment: dict[str, Any],
) -> list[str]:
    text_parts = [
        payload.get("source_key"),
        payload.get("work_item_key"),
        branch,
        pull_request.get("title"),
        commit.get("message"),
        comment.get("text"),
    ]
    keys: list[str] = []
    for value in text_parts:
        if not value:
            continue
        for match in JIRA_KEY_RE.findall(str(value)):
            if match not in keys:
                keys.append(match)
    return keys[:20]
