"""Bitbucket tools of the PR review bot on both deployments (concept §7).

- ``list_bitbucket_pull_request_heads``: every open pull request of a repository with its head commit, branches,
  draft flag and the source repository (a fork's differs), page by page;
- ``post_bitbucket_pull_request_review``: the summary comment (found again by its marker and edited in place), the
  inline comments and the build status ``octryx-review`` of the head commit (``INPROGRESS`` while the review runs,
  then ``SUCCESSFUL`` or ``FAILED``).

Server/Data Center: comments are found in the pull request's activities and edited with their ``version``; an
inline comment is anchored with ``{path, line, lineType, fileType: TO}``; the status goes to
``/rest/build-status/1.0/commits/<sha>``. Cloud: ``_bitbucket_cloud_review``. Both need a status ``url``: the run's
page when the platform has one, else the pull request's own page.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.project_resource_policy import require_project_repository_operation
from . import _bitbucket_cloud_review as cloud_review
from . import _bitbucket_internal_network
from . import _bitbucket_pr_comments as pr_comments
from . import _bitbucket_review_threads as threads
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_failure
from ._bitbucket_delivery import COMMIT, PR_ID, _repository
from ._bitbucket_internal_network import _bitbucket_json_post, _bitbucket_json_put
from ._bitbucket_write_gate import bitbucket_write_refusal

PAGE = 100
STATES = {"pending": "INPROGRESS", "success": "SUCCESSFUL", "failure": "FAILED", "error": "FAILED"}
STATUS_KEY, STATUS_NAME = "octryx-review", "Octryx review"
MAX_COMMENT = 32_000
LINE_TYPES = frozenset({"ADDED", "CONTEXT"})


def _server_head(pr: dict[str, Any]) -> dict[str, Any]:
    source, target = pr.get("fromRef") or {}, pr.get("toRef") or {}

    def repo(ref: dict[str, Any]) -> str:
        repository = ref.get("repository") or {}
        return f"{(repository.get('project') or {}).get('key') or ''}/{repository.get('slug') or ''}".strip("/")

    links = (pr.get("links") or {}).get("self") or [{}]
    return {"number": pr.get("id"), "head_sha": source.get("latestCommit"), "source_branch": source.get("displayId"),
            "target_branch": target.get("displayId"), "head_repository": repo(source), "repository": repo(target),
            "title": pr.get("title"), "author": ((pr.get("author") or {}).get("user") or {}).get("name"),
            "url": links[0].get("href") if links else "", "draft": bool(pr.get("draft"))}


async def _server_pages(context: ToolContext, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start = 0
    while True:
        page = await _bitbucket_internal_network._bitbucket_json_get(context, path, params={**params, "start": start, "limit": PAGE})
        items.extend(item for item in (page or {}).get("values") or [] if isinstance(item, dict))
        if (page or {}).get("isLastPage", True) or (page or {}).get("nextPageStart") is None:
            return items
        start = int(page["nextPageStart"])


class ListBitbucketPullRequestHeads:
    name = "list_bitbucket_pull_request_heads"
    description = "Every open pull request of an allowed Bitbucket repository with its head commit and branches."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_key, repo_slug, refused = _repository(params, context)
        if refused:
            return refused
        since = str(params.get("comments_since") or "").strip()
        answer: dict[str, Any] = {"project_key": project_key, "repo_slug": repo_slug}
        try:
            if cloud_context(context):
                pulls = await cloud_review.heads(context, project_key, repo_slug)
            else:
                path = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
                pulls = [_server_head(pr) for pr in await _server_pages(context, path, {"state": "OPEN"})]
            # The ``@octryx`` commands (stage D): a local installation gets no webhook, so the bot polls.
            numbers = [str(pr.get("number")) for pr in pulls if str(pr.get("number") or "").isdigit()]
            if since and cloud_context(context):
                answer["comments"] = await pr_comments.cloud_comments(context, project_key, repo_slug, numbers, since)
            elif since:
                answer["comments"] = await pr_comments.server_comments(
                    lambda path, extra: _server_pages(context, path, extra),
                    f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}", numbers, since)
        except CloudApiError as error:
            return cloud_failure(error)
        return {**answer, "pull_requests": pulls}


async def _server_summary(context: ToolContext, base: str, text: str, marker: str) -> dict[str, Any]:
    activities = await _server_pages(context, f"{base}/activities", {})
    mine = next((item.get("comment") for item in activities if item.get("action") == "COMMENTED" and marker
                 and marker in str((item.get("comment") or {}).get("text") or "")), None)
    if mine:
        await _bitbucket_json_put(context, f"{base}/comments/{mine['id']}",
                                  payload={"text": text, "version": mine.get("version", 0)})
        return {"summary_comment_id": mine["id"], "summary": "updated"}
    created, _ = await _bitbucket_json_post(context, f"{base}/comments", payload={"text": text})
    return {"summary_comment_id": (created or {}).get("id"), "summary": "created"}


async def _server_inline(context: ToolContext, base: str, comments: list[dict[str, Any]]) -> list[Any]:
    ids = []
    for comment in comments:
        line_type = comment.get("line_type") if comment.get("line_type") in LINE_TYPES else "ADDED"
        created, _ = await _bitbucket_json_post(context, f"{base}/comments", payload={"text": comment["body"], "anchor": {
            "path": comment["path"], "line": comment["line"], "lineType": line_type, "fileType": "TO",
            "diffType": "EFFECTIVE"}})
        ids.append((created or {}).get("id"))
    return ids


def _comments(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    return [{**item, "body": str(item.get("body") or "")[:MAX_COMMENT]} for item in items
            if isinstance(item, dict) and str(item.get("path") or "").strip() and type(item.get("line")) is int
            and item["line"] >= 1]


def _status(raw: Any) -> dict[str, Any] | None:
    status = raw if isinstance(raw, dict) else {}
    state = STATES.get(str(status.get("state") or "").lower())
    url = str(status.get("target_url") or "").strip()
    if state is None or not url.startswith("https://"):
        return None
    return {"key": STATUS_KEY, "name": STATUS_NAME, "state": state, "url": url,
            "description": str(status.get("description") or "")[:255]}


async def _post(context: ToolContext, project_key: str, repo_slug: str, pr_id: str, commit: str,
                params: dict) -> dict[str, Any]:
    summary, marker = str(params.get("summary") or "").strip(), str(params.get("marker") or "")
    comments, status, result = _comments(params.get("comments")), _status(params.get("commit_status")), {}
    reply = str(params.get("comment") or "").strip()[:MAX_COMMENT]  # a reply to an ``@octryx`` command (stage D)
    answers = [item for item in params.get("thread_answers") or [] if isinstance(item, dict)
               and str(item.get("comment_id") or "").isdigit()]
    if cloud_context(context):
        if summary:
            result.update(await cloud_review.upsert_summary(context, project_key, repo_slug, pr_id,
                                                            summary[:MAX_COMMENT], marker))
        if reply:
            result["comment_id"] = await cloud_review.conversation_comment(context, project_key, repo_slug, pr_id,
                                                                           reply)
        if comments:
            result["inline_ids"] = await cloud_review.inline(context, project_key, repo_slug, pr_id, comments)
        if answers:
            result["threads"] = await threads.cloud_answers(context, project_key, repo_slug, pr_id, answers)
        if status:
            await cloud_review.build_status(context, project_key, repo_slug, commit, status)
    else:
        base = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}"
        if summary:
            result.update(await _server_summary(context, base, summary[:MAX_COMMENT], marker))
        if reply:
            created, _ = await _bitbucket_json_post(context, f"{base}/comments", payload={"text": reply})
            result["comment_id"] = (created or {}).get("id")
        if comments:
            result["inline_ids"] = await _server_inline(context, base, comments)
        if answers:
            result["threads"] = await threads.server_answers(context, base, answers)
        if status:
            await _bitbucket_json_post(context, f"/rest/build-status/1.0/commits/{commit}", payload=status)
    if "inline_ids" in result:
        result["inline_posted"] = len(result["inline_ids"])
    return {**result, **({"commit_status": status["state"]} if status else {})}


class PostBitbucketPullRequestReview:
    name = "post_bitbucket_pull_request_review"
    description = ("Post the Octryx review on a pull request of an allowed Bitbucket repository: summary comment, "
                   "inline comments and the octryx-review build status.")

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_key, repo_slug, refused = _repository(params, context)
        if refused:
            return refused
        pr_id, commit = str(params.get("pr_id") or "").strip(), str(params.get("commit") or "").strip()
        if not PR_ID.fullmatch(pr_id) or not COMMIT.fullmatch(commit):
            return {"error": "pr_id is a pull request number and commit a commit SHA"}
        try:
            await require_project_repository_operation(
                context.db, project_ids=context.project_ids, provider="bitbucket", operation="pr",
                repository_refs=[repo_slug, f"{project_key}/{repo_slug}"])
        except HTTPException as exc:
            return {"error": exc.detail}
        if refused := await bitbucket_write_refusal(context, project_key=project_key, repo_slug=repo_slug):
            return refused
        try:
            posted = await _post(context, project_key, repo_slug, pr_id, commit, params)
        except CloudApiError as error:
            return cloud_failure(error)
        return {"status": "posted", "project_key": project_key, "repo_slug": repo_slug, "pr_id": pr_id,
                "commit": commit, **posted}


__all__ = ["ListBitbucketPullRequestHeads", "PostBitbucketPullRequestReview"]
