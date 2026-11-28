"""The review bot's inline threads on Bitbucket: the answer to a finding a later pass found fixed or still open, as a
reply in its thread and, when asked, the thread resolved."""

from __future__ import annotations

from typing import Any

import httpx

from app.tools.context import ToolContext

from . import _bitbucket_internal_network
from ._bitbucket_cloud import CloudApiError, cloud_request, repo_path
from ._bitbucket_internal_network import _bitbucket_json_post, _bitbucket_json_put

MAX_REPLY = 2000


def _why(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"status_code {error.response.status_code}"
    return str(error)[:200] or type(error).__name__


async def _answer(answers: list[dict[str, Any]], reply: Any, resolve: Any) -> list[dict[str, Any]]:
    done: list[dict[str, Any]] = []
    for answer in answers:
        comment_id = str(answer.get("comment_id") or "")
        result: dict[str, Any] = {"comment_id": comment_id, "replied": False, "resolved": False}
        try:
            text = str(answer.get("reply") or "").strip()[:MAX_REPLY]
            if text:
                await reply(comment_id, text)
                result["replied"] = True
            if answer.get("resolve") is True:
                reason = await resolve(comment_id)
                result.update({"resolved": True} if not reason else {"reason": reason})
        except (httpx.HTTPError, CloudApiError, ValueError) as error:
            result["reason"] = _why(error)
        done.append(result)
    return done


async def cloud_answers(context: ToolContext, workspace: str, slug: str, pr_id: str,
                        answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path = f"{repo_path(workspace, slug)}/pullrequests/{pr_id}/comments"

    async def reply(comment_id: str, text: str) -> None:
        await cloud_request(context, "POST", path, payload={"content": {"raw": text}, "parent": {"id": int(comment_id)}})

    async def resolve(comment_id: str) -> str:
        await cloud_request(context, "POST", f"{path}/{int(comment_id)}/resolve")
        return ""

    return await _answer(answers, reply, resolve)


async def server_answers(context: ToolContext, base: str, answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def reply(comment_id: str, text: str) -> None:
        await _bitbucket_json_post(context, f"{base}/comments", payload={"text": text, "parent": {
            "id": int(comment_id)}})

    async def resolve(comment_id: str) -> str:
        comment = await _bitbucket_internal_network._bitbucket_json_get(context, f"{base}/comments/{int(comment_id)}")
        if (comment or {}).get("threadResolved") is True:
            return ""
        updated, _ = await _bitbucket_json_put(context, f"{base}/comments/{int(comment_id)}", payload={
            "text": (comment or {}).get("text") or "", "version": (comment or {}).get("version", 0),
            "threadResolved": True})
        return "" if (updated or {}).get("threadResolved") is True else "this server cannot resolve threads"

    return await _answer(answers, reply, resolve)


__all__ = ["cloud_answers", "server_answers"]
