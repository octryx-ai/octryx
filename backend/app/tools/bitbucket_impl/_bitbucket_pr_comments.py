"""Pull request comments on Bitbucket since a time, for the review bot's ``@octryx`` commands (stage D)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.tools.context import ToolContext

from ._bitbucket_cloud import cloud_request, repo_path

PAGE = 50


def _millis(since: str) -> int:
    try:
        moment = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return int((moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp() * 1000)


async def cloud_comments(context: ToolContext, workspace: str, slug: str, pr_ids: list[str],
                         since: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for pr_id in pr_ids:
        path, page = f"{repo_path(workspace, slug)}/pullrequests/{int(pr_id)}/comments", 1
        while True:
            answer = await cloud_request(context, "GET", path, params={
                "q": f'created_on>"{since}"', "pagelen": PAGE, "page": page})
            for item in (answer or {}).get("values") or []:
                if not isinstance(item, dict) or item.get("deleted"):
                    continue
                user = item.get("user") or {}
                found.append({"id": str(item.get("id") or ""), "pr": str(pr_id),
                              "author": str(user.get("nickname") or user.get("display_name") or ""),
                              "author_id": str(user.get("account_id") or ""),
                              "body": str((item.get("content") or {}).get("raw") or ""),
                              "created_at": str(item.get("created_on") or ""),
                              "in_reply_to": str((item.get("parent") or {}).get("id") or ""),
                              "inline": bool(item.get("inline"))})
            if not (answer or {}).get("next"):
                break
            page += 1
    return found


def _server_comment(comment: dict[str, Any], pr_id: str, parent: str, inline: bool,
                    after: int) -> list[dict[str, Any]]:
    author = comment.get("author") or {}
    created = int(comment.get("createdDate") or 0)
    own = [{"id": str(comment.get("id") or ""), "pr": pr_id, "author": str(author.get("name") or ""),
            "author_id": "", "body": str(comment.get("text") or ""),  # Server/DC links people by username
            "created_at": datetime.fromtimestamp(created / 1000, UTC).isoformat() if created else "",
            "in_reply_to": parent, "inline": inline}] if created > after else []
    for reply in comment.get("comments") or []:
        if isinstance(reply, dict):
            own += _server_comment(reply, pr_id, str(comment.get("id") or ""), inline, after)
    return own


async def server_comments(pages: Any, repo_base: str, pr_ids: list[str], since: str) -> list[dict[str, Any]]:
    after, found = _millis(since), []
    for pr_id in pr_ids:
        for activity in await pages(f"{repo_base}/pull-requests/{int(pr_id)}/activities", {}):
            if activity.get("action") == "COMMENTED" and isinstance(activity.get("comment"), dict):
                found += _server_comment(activity["comment"], str(pr_id), "", bool(activity.get("commentAnchor")),
                                         after)
    unique = {item["id"]: item for item in found if item["id"]}
    return sorted(unique.values(), key=lambda item: item["created_at"])


__all__ = ["cloud_comments", "server_comments"]
