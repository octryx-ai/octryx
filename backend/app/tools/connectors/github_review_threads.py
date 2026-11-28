"""The review bot's inline threads on GitHub: which comment each posted finding got, and the answer to a finding a later
pass found fixed or still open."""

from __future__ import annotations

from typing import Any

import httpx

from .common import _string

THREADS_QUERY = (
    "query($owner:String!,$repo:String!,$number:Int!,$after:String){repository(owner:$owner,name:$repo){"
    "pullRequest(number:$number){reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor}"
    "nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}")
RESOLVE_MUTATION = "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}"
MAX_REPLY = 2000


def graphql_url(base: str) -> str:
    base = base.rstrip("/")
    return f"{base[:-len('/v3')]}/graphql" if base.endswith("/api/v3") else f"{base}/graphql"


async def inline_ids(http: Any, headers: dict[str, str], base: str, number: str, review_id: Any,
                     sent: list[dict[str, Any]]) -> list[Any]:
    if not review_id or not sent:
        return [None] * len(sent)
    got: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = await http("GET", f"{base}/pulls/{number}/reviews/{review_id}/comments", headers=headers,
                           params={"per_page": 100, "page": page})
        got.extend(item for item in batch or [] if isinstance(item, dict))
        if not isinstance(batch, list) or len(batch) < 100:
            break
        page += 1
    ids: list[Any] = []
    used: set[Any] = set()
    for comment in sent:
        match = next((item.get("id") for item in got if item.get("id") not in used
                      and item.get("path") == comment.get("path") and item.get("body") == comment.get("body")), None)
        used.add(match)
        ids.append(match)
    return ids


async def _threads(http: Any, headers: dict[str, str], url: str, owner: str, repo: str,
                   number: int) -> dict[int, tuple[str, bool]]:
    found: dict[int, tuple[str, bool]] = {}
    after = None
    while True:
        answer = await http("POST", url, headers=headers, json_body={"query": THREADS_QUERY, "variables": {
            "owner": owner, "repo": repo, "number": number, "after": after}})
        if (answer or {}).get("errors"):
            raise ValueError(_string(((answer or {}).get("errors") or [{}])[0].get("message")) or "GraphQL error")
        threads = ((((answer or {}).get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get(
            "reviewThreads") or {}
        for node in threads.get("nodes") or []:
            first = ((node.get("comments") or {}).get("nodes") or [{}])[0].get("databaseId")
            if first:
                found[int(first)] = (str(node.get("id")), bool(node.get("isResolved")))
        info = threads.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return found
        after = info.get("endCursor")


def _why(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"status_code {error.response.status_code}"
    return _string(str(error))[:200] or type(error).__name__


async def answer_threads(http: Any, headers: dict[str, str], base: str, owner: str, repo: str,
                         number: str, answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done: list[dict[str, Any]] = []
    threads: dict[int, tuple[str, bool]] | None = None
    for answer in answers:
        comment_id = answer.get("comment_id")
        result = {"comment_id": comment_id, "replied": False, "resolved": False}
        try:
            reply = _string(answer.get("reply"))[:MAX_REPLY]
            if reply:
                await http("POST", f"{base}/pulls/{number}/comments/{int(comment_id)}/replies", headers=headers,
                           json_body={"body": reply})
                result["replied"] = True
            if answer.get("resolve") is True:
                if threads is None:
                    threads = await _threads(http, headers, graphql_url(base.rsplit("/repos/", 1)[0]), owner, repo,
                                             int(number))
                thread = threads.get(int(comment_id))
                if thread is None:
                    result["reason"] = "thread not found"
                elif thread[1]:
                    result["resolved"] = True  # someone resolved it already
                else:
                    resolved = await http("POST", graphql_url(base.rsplit("/repos/", 1)[0]), headers=headers,
                                          json_body={"query": RESOLVE_MUTATION, "variables": {"id": thread[0]}})
                    if (resolved or {}).get("errors"):
                        raise ValueError(_string(resolved["errors"][0].get("message")) or "GraphQL error")
                    result["resolved"] = True
        except (httpx.HTTPError, ValueError, TypeError) as error:
            result["reason"] = _why(error)
        done.append(result)
    return done


__all__ = ["answer_threads", "graphql_url", "inline_ids"]
