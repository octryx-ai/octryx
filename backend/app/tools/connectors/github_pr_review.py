"""GitHub tools of the PR review bot: read the open pull requests' heads, post a review.

- ``list_github_pull_request_heads``: every open pull request of a repository with its head commit, branches, draft
  flag and the head's repository (a fork's differs), page by page until GitHub has no more (the hourly sync must see
  each one, not the first page);
- ``post_github_pull_request_review``: on the pull request's head commit, in this order:

  1. the summary comment, found again by its marker and edited in place, so a pull request carries one summary;
  2. the inline comments as one review (``event: COMMENT``; the bot never approves and never requests changes, so
     it never blocks a merge by itself). GitHub refuses the whole review when one comment is off the diff (422): the
     review is then posted without the inline comments and the step says so (``inline_refused``), never a silent
     loss — the summary already carries every finding's count;
  3. the commit status ``octryx/review`` (``pending`` while the review runs, then ``success`` or ``failure``).

The connection's token may be a personal access token: a commit status needs only ``repo:status``, a check run would
need a GitHub App (once one is registered, the status becomes a check run).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ...services.outbound_egress import CONNECTION_GITHUB
from ..context import ToolContext
from .common import _string, connection_http_json
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .github_pr_comments import comments_since, permissions, recently_closed, updated_since
from .github_review_threads import answer_threads, inline_ids
from .github_source_control_common import require_github_repository_operation

_http_json = connection_http_json(CONNECTION_GITHUB)
PAGE = 100
STATUS_STATES = frozenset({"pending", "success", "failure", "error"})
MAX_DESCRIPTION = 140  # GitHub's own bound of a status description
MAX_COMMENT = 65_000  # GitHub's own bound of a comment body (65,536 characters)


def _head(pr: dict[str, Any]) -> dict[str, Any]:
    head, base = pr.get("head") or {}, pr.get("base") or {}
    return {
        "number": pr.get("number"), "head_sha": head.get("sha"), "source_branch": head.get("ref"),
        "target_branch": base.get("ref"), "head_repository": (head.get("repo") or {}).get("full_name") or "",
        "repository": (base.get("repo") or {}).get("full_name") or "", "title": pr.get("title"),
        "author": (pr.get("user") or {}).get("login"), "url": pr.get("html_url"), "draft": bool(pr.get("draft")),
    }


async def _pages(context: ToolContext, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = await _http_json("GET", url, headers=await _github_headers(context),
                                 params={**params, "per_page": PAGE, "page": page})
        items.extend(item for item in batch or [] if isinstance(item, dict))
        if not isinstance(batch, list) or len(batch) < PAGE:
            return items
        page += 1


class ListGitHubPullRequestHeadsTool:
    name = "list_github_pull_request_heads"
    description = "Every open pull request of an allowed GitHub repository with its head commit and branches."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        if denied := await require_github_repository_operation(context, owner=owner, repo=repo, operation="read"):
            return denied
        base = f"{_github_base_url(context)}/repos/{owner}/{repo}"
        raw = await _pages(context, f"{base}/pulls", {"state": "open"})
        pulls = [_head(pr) for pr in raw]
        answer: dict[str, Any] = {"repository": f"{owner}/{repo}", "pull_requests": pulls}
        # The ``@octryx`` commands: a local installation gets no webhook, so the bot polls the comments;
        # a person's comment is a correction too, also on a pull request closed or merged within the last day.
        since = _string(params.get("comments_since"))
        if since:
            headers = await _github_headers(context)
            closed = await recently_closed(_http_json, headers, base)
            answer["closed_pull_requests"] = [str(pr.get("number")) for pr in closed]
            answer["comments"] = await comments_since(
                _http_json, headers, base, since, {str(pr.get("number")) for pr in [*raw, *closed]},
                reviewed=updated_since([*raw, *closed], since))
        logins = [_string(item) for item in params.get("permissions_for") or [] if _string(item)]
        if logins:
            answer["permissions"] = await permissions(_http_json, await _github_headers(context), base, logins)
        return answer


async def _upsert_summary(context: ToolContext, base: str, number: str, text: str, marker: str) -> dict[str, Any]:
    comments = await _pages(context, f"{base}/issues/{number}/comments", {})
    mine = next((item for item in comments if marker and marker in str(item.get("body") or "")), None)
    headers = await _github_headers(context)
    if mine is not None:
        edited = await _http_json("PATCH", f"{base}/issues/comments/{mine['id']}", headers=headers,
                                  json_body={"body": text})
        return {"summary_comment_id": (edited or {}).get("id") or mine["id"], "summary": "updated"}
    created = await _http_json("POST", f"{base}/issues/{number}/comments", headers=headers, json_body={"body": text})
    return {"summary_comment_id": (created or {}).get("id"), "summary": "created"}


def _review_comment(item: dict[str, Any]) -> dict[str, Any] | None:
    path, line = _string(item.get("path")), item.get("line")
    if not path or type(line) is not int or line < 1:
        return None
    comment = {"path": path, "line": line, "side": "RIGHT", "body": _string(item.get("body"))[:MAX_COMMENT]}
    start = item.get("start_line")
    if type(start) is int and 0 < start < line:
        comment.update(start_line=start, start_side="RIGHT")
    return comment


async def _review(context: ToolContext, base: str, number: str, commit: str,
                  comments: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"commit_id": commit, "event": "COMMENT", "body": "", "comments": comments}
    url, headers = f"{base}/pulls/{number}/reviews", await _github_headers(context)
    try:
        review = await _http_json("POST", url, headers=headers, json_body=payload)
        return {"review_id": (review or {}).get("id"), "inline_posted": len(comments)}
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 422:
            raise
        return {"inline_posted": 0, "inline_refused": error.response.text[:500]}


class PostGitHubPullRequestReviewTool:
    name = "post_github_pull_request_review"
    description = ("Post the Octryx review on a pull request of an allowed GitHub repository: summary comment, "
                   "inline comments and the octryx/review commit status.")

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        number, commit = _string(params.get("pr_number")), _string(params.get("commit"))
        if not owner or not repo or not number.isdigit() or not commit:
            return {"error": "repository, pr_number and commit are required and repository must be allowed"}
        if denied := await require_github_repository_operation(context, owner=owner, repo=repo, operation="pr"):
            return denied
        base, result = f"{_github_base_url(context)}/repos/{owner}/{repo}", {"status": "posted"}
        summary = _string(params.get("summary"))
        if summary:
            result.update(await _upsert_summary(context, base, number, summary[:MAX_COMMENT],
                                                _string(params.get("marker"))))
        comment = _string(params.get("comment"))
        if comment:  # a reply to an ``@octryx`` command in the conversation
            created = await _http_json("POST", f"{base}/issues/{number}/comments",
                                       headers=await _github_headers(context), json_body={"body": comment[:MAX_COMMENT]})
            result["comment_id"] = (created or {}).get("id")
        raw = params.get("comments") if isinstance(params.get("comments"), list) else []
        comments = [comment for item in raw if isinstance(item, dict) and (comment := _review_comment(item))]
        if comments:
            result.update(await _review(context, base, number, commit, comments))
            if result.get("review_id"):
                result["inline_ids"] = await inline_ids(_http_json, await _github_headers(context), base, number,
                                                        result["review_id"], comments)
        answers = [item for item in params.get("thread_answers") or [] if isinstance(item, dict)
                   and str(item.get("comment_id") or "").isdigit()]
        if answers:
            result["threads"] = await answer_threads(_http_json, await _github_headers(context), base, owner, repo,
                                                     number, answers)
        status = params.get("commit_status") if isinstance(params.get("commit_status"), dict) else {}
        state = _string(status.get("state")).lower()
        if state in STATUS_STATES:
            payload = {"state": state, "context": _string(status.get("context")) or "octryx/review",
                       "description": _string(status.get("description"))[:MAX_DESCRIPTION]}
            if _string(status.get("target_url")).startswith("https://"):
                payload["target_url"] = _string(status["target_url"])
            await _http_json("POST", f"{base}/statuses/{quote(commit, safe='')}",
                             headers=await _github_headers(context), json_body=payload)
            result["commit_status"] = state
        return {"repository": f"{owner}/{repo}", "pr_number": number, "commit": commit, **result}


__all__ = ["ListGitHubPullRequestHeadsTool", "PostGitHubPullRequestReviewTool"]
