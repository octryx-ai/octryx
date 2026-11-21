"""The threads of the bot's inline comments across passes.

- ``answer``: before an incremental pass posts its summary, the threads of findings it found fixed get "Fixed in"
  and are resolved, and a finding still open gets one reply with the reviewer's evidence
  (``incremental.thread_answers``); one post tool call, through the repository's governed connection;
- ``note``: the outcome for the summary's footer, naming a thread that could not be answered with its reason;
- ``remember``: which comment each posted finding got (the tools return ``inline_ids`` in the order sent) and which
  findings were answered, kept on the run's ``open_findings`` for the next pass.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..workflow_runs.platform.dispatch import ToolOutcome
from .incremental import Effective, thread_answers
from .render import InlineComment


async def answer(post: Callable[..., Awaitable[ToolOutcome]], passed: Effective | None,
                 sha: str) -> list[dict[str, Any]]:
    """``{id, comment_id, resolve, replied, resolved, reason}`` per answered thread; ``[]`` on a full pass."""
    planned = thread_answers(passed, sha) if passed is not None else []
    if not planned:
        return []
    outcome = await post(thread_answers=[{key: item[key] for key in ("comment_id", "reply", "resolve")}
                                         for item in planned])
    if not outcome.ok:
        return [{**item, "replied": False, "resolved": False, "reason": outcome.reason or "not posted"}
                for item in planned]
    done = {str(item.get("comment_id")): item for item in outcome.result.get("threads") or []
            if isinstance(item, dict)}
    return [{**item, **{key: value for key, value in done.get(item["comment_id"], {
        "reason": "no answer from the tool"}).items() if key != "comment_id"}} for item in planned]


def note(answered: list[dict[str, Any]]) -> str:
    """``2 threads resolved · 1 thread not answered (status_code 403)``; ``''`` when nothing was answered."""
    resolved = sum(1 for item in answered if item.get("resolve") and item.get("resolved"))
    failed = [item for item in answered if item.get("reason")]
    parts = [f"{resolved} thread(s) resolved"] if resolved else []
    if failed:
        reasons = sorted({str(item["reason"]) for item in failed})
        parts.append(f"{len(failed)} thread(s) not answered ({'; '.join(reasons)[:160]})")
    return " · ".join(parts)


def remember(reviewer: list[dict[str, Any]], comments: list[InlineComment], ids: Any,
             answered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The reviewer's open findings with the comment each got and whether its thread was answered."""
    posted = {comment.finding_id: str(ident) for comment, ident in zip(comments, ids if isinstance(ids, list) else [],
                                                                       strict=False)
              if comment.finding_id and ident}
    replied = {str(item.get("id")) for item in answered if item.get("replied") and not item.get("resolve")}
    kept = []
    for item in reviewer:
        item = dict(item)
        ident = str(item.get("id") or "")
        if ident in posted and not item.get("comment_id"):
            item["comment_id"] = posted[ident]
        if ident in replied:
            item["answered"] = True
        kept.append(item)
    return kept


__all__ = ["answer", "note", "remember"]
