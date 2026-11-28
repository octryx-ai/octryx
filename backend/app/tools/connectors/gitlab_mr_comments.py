"""Merge request notes, discussions and member access on GitLab, for the review bot (threads and ``@octryx``
commands)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

PAGE = 100
MAX_REPLY = 2000
#: A GitLab discussion id (40 hex characters today); the bot never sends anything else into a URL.
DISCUSSION_ID = re.compile(r"^[0-9A-Za-z]{1,64}$")
#: GitLab's access levels (``Gitlab::Access``) in the review bot's permission words (``commands.WRITE_LEVELS``).
ACCESS_LEVELS = ((50, "admin"), (40, "maintain"), (30, "write"), (5, "read"))


async def pages(http: Any, headers: dict[str, str], url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = await http("GET", url, headers=headers, params={**params, "per_page": PAGE, "page": page})
        items.extend(item for item in batch or [] if isinstance(item, dict))
        if not isinstance(batch, list) or len(batch) < PAGE:
            return items
        page += 1


def _moment(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _notes(discussion: dict[str, Any], iid: str, after: datetime) -> list[dict[str, Any]]:
    thread = "" if discussion.get("individual_note") else str(discussion.get("id") or "")
    found = []
    for note in discussion.get("notes") or []:
        created = _moment(str((note or {}).get("created_at") or "")) if isinstance(note, dict) else None
        if created is None or created < after or note.get("system"):
            continue
        found.append({"id": str(note.get("id") or ""), "pr": iid,
                      "author": str((note.get("author") or {}).get("username") or ""), "author_id": "",
                      "body": str(note.get("body") or ""), "created_at": created.isoformat(),
                      "in_reply_to": thread, "inline": note.get("type") == "DiffNote" or bool(note.get("position"))})
    return found


async def comments_since(http: Any, headers: dict[str, str], base: str, since: str,
                         iids: list[str]) -> list[dict[str, Any]]:
    after = _moment(since)
    if after is None:
        return []
    found: list[dict[str, Any]] = []
    for iid in iids:
        for discussion in await pages(http, headers, f"{base}/merge_requests/{quote(iid, safe='')}/discussions", {}):
            found += _notes(discussion, iid, after)
    unique = {item["id"]: item for item in found if item["id"]}
    return sorted(unique.values(), key=lambda item: item["created_at"])


def _level(access: Any) -> str:
    value = access if type(access) is int else 0
    return next((name for floor, name in ACCESS_LEVELS if value >= floor), "none")


async def permissions(http: Any, headers: dict[str, str], base: str, usernames: list[str]) -> dict[str, str]:
    levels: dict[str, str] = {}
    for username in dict.fromkeys(name for name in usernames if name):
        try:
            members = await http("GET", f"{base}/members/all", headers=headers, params={"query": username})
        except httpx.HTTPStatusError:
            levels[username] = "unknown"
            continue
        match = next((item for item in members or [] if isinstance(item, dict)
                      and str(item.get("username") or "").lower() == username.lower()), None)
        levels[username] = _level(match.get("access_level")) if match else "none"
    return levels


def _why(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"status_code {error.response.status_code}"
    return str(error)[:200] or type(error).__name__


async def answer_threads(http: Any, headers: dict[str, str], mr_base: str,
                         answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done: list[dict[str, Any]] = []
    for answer in answers:
        discussion = str(answer.get("comment_id") or "")
        result: dict[str, Any] = {"comment_id": discussion, "replied": False, "resolved": False}
        url = f"{mr_base}/discussions/{quote(discussion, safe='')}"
        try:
            text = str(answer.get("reply") or "").strip()[:MAX_REPLY]
            if text:
                await http("POST", f"{url}/notes", headers=headers, json_body={"body": text})
                result["replied"] = True
            if answer.get("resolve") is True:
                await http("PUT", url, headers=headers, params={"resolved": "true"})
                result["resolved"] = True
        except (httpx.HTTPError, ValueError) as error:
            result["reason"] = _why(error)
        done.append(result)
    return done


__all__ = ["DISCUSSION_ID", "answer_threads", "comments_since", "pages", "permissions"]
