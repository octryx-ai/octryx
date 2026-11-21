"""Pull request comments and commenter permissions on GitHub, for the review bot's ``@octryx`` commands.

A local installation gets no webhook (GitHub cannot reach it), so the bot polls (``pr_review_bot.commands``):

- ``comments_since``: every comment on the listed pull requests since a time, repository-wide in two lists (each read
  page by page): conversation comments (``GET /issues/comments?since=``, only those on a listed pull request) and
  review comments (``GET /pulls/comments?since=``, with the thread they answer); and the summary of each review
  submitted since then (``GET /pulls/{n}/reviews``, only for a pull request updated since; "Request changes" with a
  text is a correction too), as ``review-<id>``;
- ``recently_closed``: the pull requests closed or merged in the last :data:`CLOSED_WINDOW` (``state=closed``, newest
  update first, read until older): the e2e harness merges or closes its pull requests within minutes, and a comment
  written just before is still a person's correction;
- ``permissions``: a commenter's permission on the repository
  (``GET /collaborators/{login}/permission``: ``admin`` / ``maintain`` / ``write`` / ``triage`` / ``read`` /
  ``none``); ``unknown`` when the token may not read it.

Every comment is returned as ``{id, pr, author, author_id, body, created_at, in_reply_to, inline}``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

PAGE = 100
CLOSED_WINDOW = timedelta(hours=24)


def _moment(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def updated_since(pulls: list[dict[str, Any]], since: str) -> set[str]:
    """The numbers of the pull requests updated since ``since`` (a submitted review updates its pull request)."""
    start = _moment(since)
    return {str(pr.get("number")) for pr in pulls
            if start is None or ((moment := _moment(pr.get("updated_at"))) is not None and moment >= start)}


async def recently_closed(http: Any, headers: dict[str, str], base: str, *,
                          now: datetime | None = None) -> list[dict[str, Any]]:
    """The pull requests closed or merged within :data:`CLOSED_WINDOW`, raw."""
    cutoff, found, page = (now or datetime.now(UTC)) - CLOSED_WINDOW, [], 1
    while True:
        batch = await http("GET", f"{base}/pulls", headers=headers, params={
            "state": "closed", "sort": "updated", "direction": "desc", "per_page": PAGE, "page": page})
        rows = [item for item in batch or [] if isinstance(item, dict)]
        found += [pr for pr in rows if (closed := _moment(pr.get("closed_at"))) is not None and closed >= cutoff]
        last = _moment(rows[-1].get("updated_at")) if rows else None
        if len(rows) < PAGE or last is None or last < cutoff:
            return found
        page += 1


async def _pages(http: Any, headers: dict[str, str], url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = await http("GET", url, headers=headers, params={**params, "per_page": PAGE, "page": page})
        items.extend(item for item in batch or [] if isinstance(item, dict))
        if not isinstance(batch, list) or len(batch) < PAGE:
            return items
        page += 1


def _number(url: Any) -> str:
    return str(url or "").rstrip("/").rsplit("/", 1)[-1]


def _comment(item: dict[str, Any], pr: str, *, inline: bool) -> dict[str, Any]:
    user = item.get("user") or {}
    return {"id": str(item.get("id") or ""), "pr": pr, "author": str(user.get("login") or ""),
            "author_id": str(user.get("id") or ""), "body": str(item.get("body") or ""),
            "created_at": str(item.get("created_at") or ""),
            "in_reply_to": str(item.get("in_reply_to_id") or ""), "inline": inline}


def _review(item: dict[str, Any], pr: str) -> dict[str, Any]:
    return {**_comment(item, pr, inline=False), "id": f"review-{item.get('id')}",
            "created_at": str(item.get("submitted_at") or ""), "review": True}


async def comments_since(http: Any, headers: dict[str, str], base: str, since: str, numbers: set[str],
                         reviewed: set[str] | None = None) -> list[dict[str, Any]]:
    """The comments on the pull requests ``numbers`` created or edited since ``since`` (ISO 8601), and the review
    summaries with a text submitted since then on ``reviewed`` (the ones of them updated since)."""
    params = {"since": since, "sort": "created", "direction": "asc"}
    found = [_comment(item, _number(item.get("issue_url")), inline=False)
             for item in await _pages(http, headers, f"{base}/issues/comments", params)]
    found += [_comment(item, _number(item.get("pull_request_url")), inline=True)
              for item in await _pages(http, headers, f"{base}/pulls/comments", params)]
    start = _moment(since)
    for number in sorted(reviewed or set()):
        for item in await _pages(http, headers, f"{base}/pulls/{quote(number, safe='')}/reviews", {}):
            submitted = _moment(item.get("submitted_at"))
            if str(item.get("body") or "").strip() and str(item.get("state") or "") != "PENDING" and (
                    start is None or (submitted is not None and submitted >= start)):
                found.append(_review(item, number))
    return sorted((item for item in found if item["pr"] in numbers and item["id"]), key=lambda item: item["created_at"])


async def permissions(http: Any, headers: dict[str, str], base: str, logins: list[str]) -> dict[str, str]:
    levels: dict[str, str] = {}
    for login in dict.fromkeys(login for login in logins if login):
        try:
            answer = await http("GET", f"{base}/collaborators/{quote(login, safe='')}/permission", headers=headers)
            levels[login] = str((answer or {}).get("permission") or "none")
        except httpx.HTTPStatusError as error:
            levels[login] = "none" if error.response.status_code == 404 else "unknown"
    return levels


__all__ = ["CLOSED_WINDOW", "comments_since", "permissions", "recently_closed", "updated_since"]
