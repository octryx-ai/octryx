"""Bitbucket Cloud operations of the PR review bot (REST 2.0), in the shapes the review tools return.

- **heads**: ``pullrequests?state=OPEN`` page by page (``page`` until the answer has no ``next``);
- **summary**: the pull request's comment carrying the marker is edited (``PUT comments/<id>``), else one is created;
- **inline**: ``POST comments`` with ``inline: {path, to}`` (the new side's line);
- **status**: ``POST commit/<sha>/statuses/build`` with key ``octryx-review``; Cloud requires a ``url``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.tools.context import ToolContext

from ._bitbucket_cloud import cloud_request, repo_path

PAGE = 50  # Cloud's largest page of pull requests
COMMENT_PAGE = 100


def _ref(value: str) -> str:
    return quote(str(value), safe="")


def _head(pr: dict[str, Any]) -> dict[str, Any]:
    source, target = pr.get("source") or {}, pr.get("destination") or {}
    return {
        "number": pr.get("id"), "head_sha": (source.get("commit") or {}).get("hash"),
        "source_branch": (source.get("branch") or {}).get("name"),
        "target_branch": (target.get("branch") or {}).get("name"),
        "head_repository": (source.get("repository") or {}).get("full_name") or "",
        "repository": (target.get("repository") or {}).get("full_name") or "", "title": pr.get("title"),
        "author": (pr.get("author") or {}).get("display_name"),
        "author_id": (pr.get("author") or {}).get("account_id") or "",
        "url": ((pr.get("links") or {}).get("html") or {}).get("href"), "draft": bool(pr.get("draft")),
    }


async def _pages(context: ToolContext, path: str, params: dict[str, Any], size: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = await cloud_request(context, "GET", path, params={**params, "pagelen": size, "page": page})
        items.extend(item for item in (answer or {}).get("values") or [] if isinstance(item, dict))
        if not (answer or {}).get("next"):
            return items
        page += 1


async def heads(context: ToolContext, workspace: str, slug: str) -> list[dict[str, Any]]:
    path = f"{repo_path(workspace, slug)}/pullrequests"
    return [_head(pr) for pr in await _pages(context, path, {"state": "OPEN"}, PAGE)]


async def upsert_summary(context: ToolContext, workspace: str, slug: str, pr_id: str, text: str,
                         marker: str) -> dict[str, Any]:
    path = f"{repo_path(workspace, slug)}/pullrequests/{_ref(pr_id)}/comments"
    comments = await _pages(context, path, {}, COMMENT_PAGE)
    mine = next((item for item in comments if marker and not item.get("deleted")
                 and marker in str((item.get("content") or {}).get("raw") or "")), None)
    if mine is not None:
        await cloud_request(context, "PUT", f"{path}/{_ref(mine['id'])}", payload={"content": {"raw": text}})
        return {"summary_comment_id": mine["id"], "summary": "updated"}
    created = await cloud_request(context, "POST", path, payload={"content": {"raw": text}})
    return {"summary_comment_id": (created or {}).get("id"), "summary": "created"}


async def conversation_comment(context: ToolContext, workspace: str, slug: str, pr_id: str, text: str) -> Any:
    created = await cloud_request(context, "POST", f"{repo_path(workspace, slug)}/pullrequests/{_ref(pr_id)}/comments",
                                  payload={"content": {"raw": text}})
    return (created or {}).get("id")


async def inline(context: ToolContext, workspace: str, slug: str, pr_id: str,
                 comments: list[dict[str, Any]]) -> list[Any]:
    """The id of each posted comment, in order (a later pass answers in its thread)."""
    path = f"{repo_path(workspace, slug)}/pullrequests/{_ref(pr_id)}/comments"
    ids = []
    for comment in comments:
        created = await cloud_request(context, "POST", path, payload={
            "content": {"raw": comment["body"]}, "inline": {"path": comment["path"], "to": comment["line"]}})
        ids.append((created or {}).get("id"))
    return ids


async def build_status(context: ToolContext, workspace: str, slug: str, commit: str, status: dict[str, Any]) -> None:
    await cloud_request(context, "POST", f"{repo_path(workspace, slug)}/commit/{_ref(commit)}/statuses/build",
                        payload=status)


__all__ = ["build_status", "conversation_comment", "heads", "inline", "upsert_summary"]
