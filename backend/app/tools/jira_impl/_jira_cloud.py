"""Jira Cloud and Server/Data Center differences, in one place (Jira Cloud compatibility)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

CLOUD_HOST_SUFFIX = ".atlassian.net"
CLOUD_AUTH_MODE = "cloud_api_token"
CLOUD_SEARCH_PATH = "/rest/api/3/search/jql"
CLOUD_PAGE_SIZE = 100
# Bounds the token walk an offset (``start_at``) needs on Cloud, which has no ``startAt``.
MAX_CLOUD_SEARCH_PAGES = 50
_MAX_ADF_DEPTH = 40


def is_jira_cloud(jira_url: str, config: Mapping[str, Any] | None = None) -> bool:
    host = (urlsplit(str(jira_url or "")).hostname or "").lower()
    if host.endswith(CLOUD_HOST_SUFFIX):
        return True
    mode = (config or {}).get("jira_auth_mode")
    return isinstance(mode, str) and mode.strip() == CLOUD_AUTH_MODE


@dataclass(frozen=True, slots=True)
class JiraSearchResult:
    issues: list[dict[str, Any]]
    #: The total match count where the API reports one (Server/DC); ``None`` on Cloud.
    total: int | None
    api_version: str
    #: True when no further page exists (Cloud: ``isLast`` or no token; Server/DC: the page ran out).
    is_last: bool
    #: Cloud only: the token that continues right after the returned issues (``page_token`` of the next call).
    next_page_token: str | None = None


def _field_list(fields: str | list[str] | tuple[str, ...]) -> list[str]:
    values = fields.split(",") if isinstance(fields, str) else list(fields)
    return [str(value).strip() for value in values if str(value).strip()]


async def jira_search(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    cloud: bool,
    jql: str,
    fields: str | list[str] | tuple[str, ...],
    max_results: int,
    start_at: int = 0,
    server_params: Mapping[str, Any] | None = None,
    api_get: Callable[..., Awaitable[tuple[dict[str, Any], str]]] | None = None,
    page_token: str | None = None,
) -> JiraSearchResult:
    if not cloud:
        if api_get is None:
            from . import _jira_helpers_api

            api_get = _jira_helpers_api._jira_api_get

        payload, api_version = await api_get(
            client,
            jira_url,
            "/search",
            headers=headers,
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": ",".join(_field_list(fields)),
                **dict(server_params or {}),
            },
        )
        issues = [issue for issue in payload.get("issues") or [] if isinstance(issue, dict)]
        total = payload.get("total") if type(payload.get("total")) is int else None
        is_last = not issues or (total is not None and start_at + len(issues) >= total)
        return JiraSearchResult(issues[:max_results], total, api_version, is_last)
    return await _cloud_search(
        client, jira_url, headers=headers, jql=jql, fields=_field_list(fields), max_results=max_results,
        start_at=0 if page_token else start_at, page_token=page_token,
    )


async def _cloud_search(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    jql: str,
    fields: list[str],
    max_results: int,
    start_at: int,
    page_token: str | None = None,
) -> JiraSearchResult:
    wanted = max(0, start_at) + max(0, max_results)
    collected: list[dict[str, Any]] = []
    token: str | None = page_token
    is_last = False
    for _page in range(MAX_CLOUD_SEARCH_PAGES):
        size = min(CLOUD_PAGE_SIZE, wanted - len(collected))
        body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": size}
        if token:
            body["nextPageToken"] = token
        response = await client.post(
            f"{jira_url}{CLOUD_SEARCH_PATH}", headers={**headers, "Content-Type": "application/json"}, json=body
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        page = [issue for issue in (payload.get("issues") or []) if isinstance(issue, dict)]
        collected.extend(page)
        token = payload.get("nextPageToken") if isinstance(payload.get("nextPageToken"), str) else None
        is_last = bool(payload.get("isLast")) or not token or not page
        if is_last or len(collected) >= wanted:
            break
    window = collected[max(0, start_at) : max(0, start_at) + max(0, max_results)]
    # The token continues exactly after the window only when the window ends where the last page ended.
    exact = len(collected) == max(0, start_at) + len(window)
    return JiraSearchResult(window, None, "3", is_last, token if (exact and not is_last) else None)


def assignee_field(user: Mapping[str, Any] | None, *, cloud: bool) -> dict[str, str] | None:
    if not isinstance(user, Mapping):
        return None
    key = "accountId" if cloud else "name"
    value = str(user.get(key) or "").strip()
    return {key: value} if value else None


def text_to_adf(text: str) -> dict[str, Any]:
    paragraphs: list[dict[str, Any]] = []
    for block in str(text or "").replace("\r\n", "\n").split("\n\n"):
        lines = block.split("\n")
        content: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if index:
                content.append({"type": "hardBreak"})
            if line:
                content.append({"type": "text", "text": line})
        paragraphs.append({"type": "paragraph", "content": content} if content else {"type": "paragraph"})
    return {"type": "doc", "version": 1, "content": paragraphs or [{"type": "paragraph"}]}


def rich_text_body(text: str, *, cloud: bool) -> str | dict[str, Any]:
    return text_to_adf(text) if cloud else str(text or "")


def readable_body(value: Any) -> Any:
    return adf_to_text(value) if isinstance(value, Mapping) else value


def adf_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping) or value.get("type") != "doc":
        return ""
    blocks = [_block(node, 0) for node in _children(value)]
    return "\n\n".join(block for block in blocks if block).strip()


def _children(node: Mapping[str, Any]) -> list[Any]:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _kind(node: Mapping[str, Any]) -> str:
    kind = node.get("type")
    return kind if isinstance(kind, str) else ""


def _attrs(node: Mapping[str, Any]) -> Mapping[str, Any]:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, Mapping) else {}


def _string(*values: Any) -> str:
    return next((value for value in values if isinstance(value, str) and value), "")


def _inline(node: Any, depth: int) -> str:
    if not isinstance(node, Mapping) or depth > _MAX_ADF_DEPTH:
        return ""
    kind = _kind(node)
    attrs = _attrs(node)
    if kind == "text":
        text = _string(node.get("text"))
        marks = node.get("marks")
        for mark in marks if isinstance(marks, list) else []:
            if not isinstance(mark, Mapping):
                continue
            if _kind(mark) == "link":
                href = _string(_attrs(mark).get("href"))
                if href:
                    text = f"[{text}]({href})"
            elif _kind(mark) == "code":
                text = f"`{text}`"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        return _string(attrs.get("text"))
    if kind == "emoji":
        return _string(attrs.get("text"), attrs.get("shortName"))
    if kind in {"inlineCard", "blockCard"}:
        return _string(attrs.get("url"))
    return "".join(_inline(child, depth + 1) for child in _children(node))


def _block(node: Any, depth: int) -> str:
    if not isinstance(node, Mapping) or depth > _MAX_ADF_DEPTH:
        return ""
    kind = _kind(node)
    children = _children(node)
    if kind == "paragraph":
        return "".join(_inline(child, depth + 1) for child in children)
    if kind == "heading":
        level = _attrs(node).get("level")
        prefix = "#" * level if type(level) is int and 1 <= level <= 6 else "#"
        return f"{prefix} {''.join(_inline(child, depth + 1) for child in children)}"
    if kind in {"bulletList", "orderedList"}:
        items = []
        for index, item in enumerate(children, start=1):
            marker = f"{index}." if kind == "orderedList" else "-"
            parts = _children(item) if isinstance(item, Mapping) else []
            text = "\n".join(filter(None, (_block(part, depth + 2) for part in parts)))
            items.append(f"{marker} {text}")
        return "\n".join(items)
    if kind == "codeBlock":
        return "```\n" + "".join(_inline(child, depth + 1) for child in children) + "\n```"
    if kind == "blockquote":
        inner = "\n\n".join(filter(None, (_block(child, depth + 1) for child in children)))
        return "\n".join(f"> {line}" for line in inner.split("\n"))
    if kind == "rule":
        return "---"
    if children:
        return "\n\n".join(filter(None, (_block(child, depth + 1) for child in children)))
    return _inline(node, depth + 1)


__all__ = [
    "CLOUD_SEARCH_PATH",
    "JiraSearchResult",
    "adf_to_text",
    "assignee_field",
    "is_jira_cloud",
    "jira_search",
    "readable_body",
    "rich_text_body",
    "text_to_adf",
]
