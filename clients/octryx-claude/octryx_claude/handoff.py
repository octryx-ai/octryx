"""The handoff routine and ``resume`` (root freeze 3c). No model call, no seat allowance.

Shared by ``/handoff`` (UserPromptSubmit hook), ``octryx-claude handoff`` (terminal) and the automatic trigger
(``handoff_now``). It talks only to the agent gateway's handoff control plane with the user's gateway login:

1. **Item** (``/handoff/prepare``): the key, ``--all``, the session's work item, its claims, or a new item.
2. **Work state** (``work_state``): the WIP branch per item, without touching the user's tree. The branch is
   pushed only under ``push: branch`` to a registered repository; otherwise, or when the push fails, a git bundle
   is uploaded (secret-scanned server-side; a refusal stops that item's handoff with a clear message).
   ``push: off`` hands over the document only.
3. **Handoff document** (``/handoff/commit``): the git facts and ``--note``; the server adds the rest.
4. **Takeover** per the Workspace policy; the routine polls a pending takeover for up to ``poll_seconds``.

:func:`run_resume` fetches the branch (or downloads and verifies the bundle), checks the exact WIP commit out in a
new worktree ``../octryx-<KEY>`` and returns the opening context for the session (the handoff, never a transcript).
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .handoff_platform import _codes, _Platform
from .platform import SessionContext
from .state import LocalState
from .work_state import (
    WorkState,
    WorkStateError,
    branch_name,
    capture_work_state,
    create_branch,
    create_bundle,
    free_branch_name,
    may_push,
    push_branch,
    repository_root,
)

POLL_SECONDS = 60.0
POLL_EVERY = 3.0


@dataclass
class ItemReport:
    key: str
    branch: str = ""
    pushed: bool = False
    bundle_id: str = ""
    version: int | None = None
    takeover: str = ""
    error: str = ""


@dataclass
class HandoffReport:
    items: list[ItemReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and all(not item.error for item in self.items)

    def lines(self) -> list[str]:
        if self.error:
            return [f"Handoff failed: {self.error}"]
        lines = []
        for item in self.items:
            if item.error:
                lines.append(f"{item.key}: not handed over ({item.error})")
                continue
            where = (f"branch {item.branch} (pushed)" if item.pushed else
                     f"branch {item.branch} (bundle on Octryx)" if item.bundle_id else
                     f"branch {item.branch} (local only)" if item.branch else "no git work state")
            lines.append(f"{item.key}: handoff v{item.version}, {where}, {item.takeover}")
        return lines + self.warnings

    def summary(self) -> str:
        return "; ".join(self.lines()) or "Nothing to hand over."


def _hand_over_work(platform: _Platform, work: WorkState, policy: dict[str, Any], repositories: list[str],
                    item: dict[str, Any], branch: str) -> tuple[dict[str, Any], ItemReport]:
    branch = free_branch_name(work.root, branch)
    report = ItemReport(key=str(item["key"]), branch=branch)
    create_branch(work.root, branch, work.wip_commit)
    push_mode = str(policy.get("push") or "branch")
    repo = {"url": work.remote_url or None, "branch": branch, "base_commit": work.base_commit,
            "wip_commit": work.wip_commit}
    if push_mode == "off":
        return repo, report
    if may_push(push_mode, work.remote_url, repositories, work.push_urls) and push_branch(work, branch, repositories):
        report.pushed = True
        return repo, report
    with tempfile.TemporaryDirectory(prefix="octryx-handoff-bundle-") as scratch:
        try:
            data = create_bundle(work, branch, Path(scratch) / "handoff.bundle")
        except WorkStateError as error:
            report.error = error.code
            return repo, report
    bundle_id, refusal = platform.upload(str(item["id"]), data)
    if refusal:
        report.error = ("the bundle contains a secret; remove it from the changes and hand over again"
                        if refusal == "secret_detected" else refusal)
        return repo, report
    report.bundle_id = repo["bundle_id"] = bundle_id
    return repo, report


def _takeover_line(platform: _Platform, takeover: Any, poll_seconds: float, sleep: Callable[[float], None],
                   clock: Callable[[], float]) -> str:
    if not isinstance(takeover, dict):
        return "handoff request posted (no takeover yet)"
    deadline = clock() + poll_seconds
    while takeover.get("status") == "pending" and clock() < deadline:
        sleep(POLL_EVERY)
        polled = platform.call("GET", f"/takeovers/{takeover.get('id')}")
        if polled.outcome == "ok" and isinstance(polled.body.get("takeover"), dict):
            takeover = polled.body["takeover"]
    status = takeover.get("status")
    receiver = ((takeover.get("to") or {}).get("user") or {}).get("display_name") or "someone"
    if status == "confirmed":
        return f"taken over by the agent of {receiver}"
    return f"takeover {status} (waiting for {receiver})" if status == "pending" else f"takeover {status}"


def run_handoff(
    state: LocalState, context: SessionContext, http: httpx.Client, *, cwd: Path | str, key: str = "",
    to_user: str = "", note: str = "", all_items: bool = False, poll_seconds: float = POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = datetime.now,
) -> HandoffReport:
    report = HandoffReport()
    platform = _Platform(state, context, http)
    prepared = platform.call("POST", "/prepare", {"key": key or None, "all": all_items})
    if prepared.outcome != "ok":
        report.error = f"prepare refused ({_codes(prepared)})"
        return report
    items = [item for item in prepared.body.get("items") or [] if isinstance(item, dict)]
    if not items:
        report.warnings.append("Nothing to hand over: no work item is held.")
        return report
    policy = prepared.body.get("policy") if isinstance(prepared.body.get("policy"), dict) else {}
    repositories = [str(url) for url in prepared.body.get("repositories") or []]
    user = prepared.body.get("user") if isinstance(prepared.body.get("user"), dict) else {}
    user_name = str(user.get("name") or "Octryx user")
    root = repository_root(cwd)
    work: WorkState | None = None
    if root is None:
        report.warnings.append("No git repository here: only the handoff document travels.")
    else:
        keys = ", ".join(str(item["key"]) for item in items)
        try:
            work = capture_work_state(root, user_name=user_name, user_email=str(user.get("email") or ""),
                                      message=f"WIP handoff of {keys}")
        except WorkStateError as error:
            report.warnings.append(f"Git work state not captured ({error.code}).")
        if work is not None and work.excluded_files:
            report.warnings.append("Left out (secret-bearing paths): " + ", ".join(work.excluded_files))
    stamp = now()
    for item in items:
        repo: dict[str, Any] = {}
        item_report = ItemReport(key=str(item["key"]))
        if work is not None:
            try:
                repo, item_report = _hand_over_work(platform, work, policy, repositories, item,
                                                    branch_name(str(item["key"]), user_name, stamp))
            except WorkStateError as error:
                item_report.error = error.code
        if item_report.error:
            report.items.append(item_report)
            continue
        git_facts = {"last_commits": work.last_commits, "changed_files": work.changed_files,
                     "excluded_files": work.excluded_files} if work is not None else {}
        committed = platform.call("POST", "/commit", {
            "work_item_id": item["id"], "repo": {k: v for k, v in repo.items() if v}, "git": git_facts,
            "note": note or None, "to_user": to_user or None,
        })
        if committed.outcome != "ok":
            item_report.error = f"handoff refused ({_codes(committed)})"
        else:
            item_report.version = (committed.body.get("handoff") or {}).get("version")
            item_report.takeover = _takeover_line(platform, committed.body.get("takeover"), poll_seconds, sleep,
                                                  clock)
        report.items.append(item_report)
    return report


__all__ = [
    "HandoffReport",
    "ItemReport",
    "run_handoff",
]
