"""The sources of corrections, each called where its event happens (contract: Settings, ``sources``).

- ``review_fixed``: the findings a follow-up review answered as fixed (``review/runner.review_one``);
- ``review_change_request``: a confirmation answered "change" with a reason that is not an answer to the agent's
  questions, and a functional acceptance rejected with a reason (``hitl_decisions``, ``documentation/acceptance``);
- ``pr_comment``: a person's pull request comment that is no ``@octryx`` command (``pr_review_bot/webhook``);
- ``pipeline_cause``: the causes of a red pipeline (``pipeline.record_report``);
- ``refused_call``: a refusal the next allowed call answered (``run_memory.denial_answered``);
- ``revert`` (stage 1b): not captured yet, it needs the repository's history.
"""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from .store import Correction, capture


async def _for_run(db: Any, run: WorkflowRun, correction: Correction) -> None:
    from ..run_memory.store import app_of

    await capture(db, getattr(run, "project_id", None), getattr(run, "repository", None), app_of(run), Correction(
        **{**correction.__dict__, "run_id": run.id, "work_item_key": str(getattr(run, "ticket_key", "") or "")}))


async def review_fixed(db: Any, run: WorkflowRun, record: dict[str, Any], **code: str) -> None:
    """``code``: ``before_tree`` / ``after_tree`` (the platform's review) or ``before_sha`` / ``after_sha`` (the PR
    review bot's incremental pass)."""
    for item in record.get("dropped") or []:
        if isinstance(item, dict) and item.get("dropped") == "fixed":
            file = str(item.get("file") or "")
            await _for_run(db, run, Correction("review_fixed", "review", str(item.get("fix") or ""), file=file,
                                               code={**code, "paths": [_bare(file)] if _bare(file) else []}))


async def change_request(db: Any, run: WorkflowRun, reason: str, user: Any, subject: str) -> None:
    await _for_run(db, run, Correction("review_change_request", "change_request", reason,
                                       people=(user,) if user is not None else ()))


async def pipeline_red(db: Any, run: WorkflowRun, *, style_errors: list[str], failed: list[str],
                       missing_proofs: list[str], base_errors: list[str], tree: str = "") -> None:
    """``tree``: the tree the red pipeline ran on (``pipeline_head.binding``), the code with the mistake."""
    for kind, messages in (("code_style", style_errors), ("test", failed), ("proof", missing_proofs),
                           ("red_on_base", base_errors)):
        for message in messages:
            path = _first_path(str(message))
            await _for_run(db, run, Correction("pipeline_cause", kind, str(message), file=path,
                                               code={"before_tree": tree, "paths": [path] if path else []}))


async def refused_call(db: Any, run: WorkflowRun, reason: str, refused: str, worked: str) -> None:
    await _for_run(db, run, Correction("refused_call", "refused_call", f"{reason}: {refused}",
                                       file=_first_path(refused)))


async def pr_comment(db: Any, project_id: str, event: Any) -> None:
    """A person's comment on a pull request of a repository the Workspace connected: its author is an SCM account
    linked to an active human with a role in the Workspace, its body none of the bot's own posts. The app is the
    repository root (a comment names no run)."""
    import re

    from ...access_control import get_project_role_for_user
    from ...pr_review_bot.commands import parse_command
    from ...pr_review_bot.seat_choice import linked_users
    from .signature import data

    rules = data()["pr_comment"]
    body = str(getattr(event, "body", "") or "").strip()
    if len(body) < int(rules["min_chars"]) or parse_command(body) is not None or any(
            re.match(pattern, body) for pattern in rules["bot_bodies"]):
        return
    people = [user for user in await linked_users(db, event.repository, event.author, getattr(event, "author_id", ""))
              if user.account_type == "human" and await get_project_role_for_user(db, user.id, project_id)]
    if not people:
        return
    await capture(db, project_id, event.repository, ".", Correction(
        "pr_comment", "pr_comment", body, people=(event.author, *people),
        ref=f"{event.repository}#{event.pr_id}/{event.comment_id}"))


def _bare(file: str) -> str:
    return file.split(":", 1)[0].strip().lstrip("./") if file and not file.startswith("(") else ""


def _first_path(text: str) -> str:
    import re

    found = re.search(r"(?:[\w.\-]+/)+[\w.\-]+\.\w+", text)
    return found.group(0) if found else ""


__all__ = ["change_request", "pipeline_red", "pr_comment", "refused_call", "review_fixed"]
