"""GitLab tools of the PR review bot: read the open merge requests' heads, post a review (concept §7)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from ...services.outbound_egress import CONNECTION_GITLAB
from ..context import ToolContext
from .common import _string, connection_http_json
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project
from .gitlab_mr_comments import DISCUSSION_ID, answer_threads, comments_since, pages, permissions
from .gitlab_source_control_common import require_gitlab_repository_operation

_http_json = connection_http_json(CONNECTION_GITLAB)
STATES = {"pending": "pending", "success": "success", "failure": "failed", "error": "failed"}
STATUS_NAME = "octryx-review"
MAX_DESCRIPTION = 255
MAX_COMMENT = 100_000  # far below GitLab's 1,000,000 characters of a note; the same order as the other providers
IID = re.compile(r"^\d{1,10}$")
COMMIT = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _head(project: str, mr: dict[str, Any]) -> dict[str, Any]:
    fork = mr.get("source_project_id") is not None and mr.get("source_project_id") != mr.get("target_project_id")
    return {
        "number": mr.get("iid"), "head_sha": mr.get("sha"), "source_branch": mr.get("source_branch"),
        "target_branch": mr.get("target_branch"),
        # A fork's path is not in the listing; its project id names it, and differs from ``project`` either way.
        "head_repository": f"project-{mr.get('source_project_id')}" if fork else project, "repository": project,
        "title": mr.get("title"), "author": (mr.get("author") or {}).get("username"), "url": mr.get("web_url"),
        "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
    }


class ListGitLabMergeRequestHeadsTool:
    name = "list_gitlab_merge_request_heads"
    description = "Every open merge request of an allowed GitLab project with its head commit and branches."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        if not project:
            return {"error": "project is required and must be allowed"}
        if denied := await require_gitlab_repository_operation(context, project=project, operation="read"):
            return denied
        base, headers = f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}", await _gitlab_headers(context)
        listed = await pages(_http_json, headers, f"{base}/merge_requests", {"state": "opened"})
        heads = [_head(project, mr) for mr in listed]
        answer: dict[str, Any] = {"project": project, "pull_requests": heads}
        # The ``@octryx`` commands (stage D): a local installation gets no webhook, so the bot polls the notes.
        since = _string(params.get("comments_since"))
        if since:
            iids = [str(head["number"]) for head in heads if str(head.get("number") or "").isdigit()]
            answer["comments"] = await comments_since(_http_json, headers, base, since, iids)
        usernames = [_string(item) for item in params.get("permissions_for") or [] if _string(item)]
        if usernames:
            answer["permissions"] = await permissions(_http_json, headers, base, usernames)
        return answer


async def _upsert_summary(mr_base: str, headers: dict[str, str], text: str, marker: str) -> dict[str, Any]:
    notes = await pages(_http_json, headers, f"{mr_base}/notes", {"sort": "asc", "order_by": "created_at"})
    mine = next((note for note in notes if marker and not note.get("system")
                 and marker in str(note.get("body") or "")), None)
    if mine is not None:
        edited = await _http_json("PUT", f"{mr_base}/notes/{int(mine['id'])}", headers=headers,
                                  json_body={"body": text})
        return {"summary_comment_id": (edited or {}).get("id") or mine["id"], "summary": "updated"}
    created = await _http_json("POST", f"{mr_base}/notes", headers=headers, json_body={"body": text})
    return {"summary_comment_id": (created or {}).get("id"), "summary": "created"}


def _comments(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    return [{**item, "body": _string(item.get("body"))[:MAX_COMMENT]} for item in items
            if isinstance(item, dict) and _string(item.get("path")) and type(item.get("line")) is int
            and item["line"] >= 1]


def _position(comment: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    path = _string(comment["path"])
    position = {"position_type": "text", "base_sha": refs.get("base_sha"), "start_sha": refs.get("start_sha"),
                "head_sha": refs.get("head_sha"), "new_path": path,
                "old_path": _string(comment.get("old_path")) or path, "new_line": comment["line"]}
    old_line = comment.get("old_line")
    if comment.get("line_type") == "CONTEXT" and type(old_line) is int and old_line >= 1:
        position["old_line"] = old_line  # an unchanged line is anchored on both sides
    return position


async def _inline(mr_base: str, headers: dict[str, str], comments: list[dict[str, Any]]) -> dict[str, Any]:
    mr = await _http_json("GET", mr_base, headers=headers)
    refs = (mr or {}).get("diff_refs") or {}
    if not refs.get("head_sha"):
        return {"inline_ids": [], "inline_posted": 0, "inline_refused": "the merge request has no diff_refs yet"}
    ids: list[Any] = []
    refused: list[str] = []
    for comment in comments:
        try:
            created = await _http_json("POST", f"{mr_base}/discussions", headers=headers,
                                       json_body={"body": comment["body"], "position": _position(comment, refs)})
            ids.append((created or {}).get("id"))
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in (400, 422):
                raise
            ids.append(None)
            refused.append(f"{comment['path']}:{comment['line']}: {error.response.text[:200]}")
    result = {"inline_ids": ids, "inline_posted": sum(1 for ident in ids if ident)}
    return {**result, "inline_refused": "; ".join(refused)[:500]} if refused else result


async def _status(base: str, headers: dict[str, str], commit: str, raw: Any) -> dict[str, Any]:
    status = raw if isinstance(raw, dict) else {}
    state = STATES.get(_string(status.get("state")).lower())
    if state is None:
        return {}
    payload = {"state": state, "name": STATUS_NAME, "description": _string(status.get("description"))[:MAX_DESCRIPTION]}
    if _string(status.get("target_url")).startswith("https://"):
        payload["target_url"] = _string(status["target_url"])
    try:
        await _http_json("POST", f"{base}/statuses/{quote(commit, safe='')}", headers=headers, json_body=payload)
    except httpx.HTTPStatusError as error:
        # GitLab refuses a status the commit already has ("Cannot transition status via :enqueue from :pending"):
        # a second review of the same head is not a failed post.
        if error.response.status_code != 400 or "transition" not in error.response.text.lower():
            raise
        return {"commit_status": state, "commit_status_unchanged": True}
    return {"commit_status": state}


class PostGitLabMergeRequestReviewTool:
    name = "post_gitlab_merge_request_review"
    description = ("Post the Octryx review on a merge request of an allowed GitLab project: summary note, inline "
                   "discussions and the octryx-review commit status.")

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        iid, commit = _string(params.get("mr_iid")), _string(params.get("commit"))
        if not project or not IID.fullmatch(iid) or not COMMIT.fullmatch(commit):
            return {"error": "project, mr_iid (a merge request iid) and commit (a SHA) are required and project "
                             "must be allowed"}
        if denied := await require_gitlab_repository_operation(context, project=project, operation="pr"):
            return denied
        base = f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}"
        mr_base, headers, result = f"{base}/merge_requests/{iid}", await _gitlab_headers(context), {}
        summary = _string(params.get("summary"))
        if summary:
            result.update(await _upsert_summary(mr_base, headers, summary[:MAX_COMMENT], _string(params.get("marker"))))
        reply = _string(params.get("comment"))
        if reply:  # a reply to an ``@octryx`` command in the merge request's overview (stage D)
            created = await _http_json("POST", f"{mr_base}/notes", headers=headers,
                                       json_body={"body": reply[:MAX_COMMENT]})
            result["comment_id"] = (created or {}).get("id")
        comments = _comments(params.get("comments"))
        if comments:
            result.update(await _inline(mr_base, headers, comments))
        answers = [item for item in params.get("thread_answers") or [] if isinstance(item, dict)
                   and DISCUSSION_ID.fullmatch(str(item.get("comment_id") or ""))]
        if answers:
            result["threads"] = await answer_threads(_http_json, headers, mr_base, answers)
        result.update(await _status(base, headers, commit, params.get("commit_status")))
        return {"status": "posted", "project": project, "mr_iid": iid, "commit": commit, **result}


__all__ = ["ListGitLabMergeRequestHeadsTool", "PostGitLabMergeRequestReviewTool"]
