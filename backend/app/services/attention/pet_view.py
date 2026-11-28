"""The Octryx pet's view of the attention queue: one state, a few items, a poll hint (Octryx companion, stage 2)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from typing import Any

VERSION = 1
MAX_ITEMS = 5
MAX_TITLE = 80
THRESHOLD_KINDS = frozenset({"budget", "allowance"})
# The seat allowance and a running session's answer are the person's, not a Workspace's.
USER_WIDE_KINDS = frozenset({"allowance", "live"})
PANEL_PATH = "/chat"
# Seconds until the pet asks again: sooner while something moves or waits for the person.
POLL_AFTER = {"needs_you": 15, "problem": 15, "working": 30, "done": 60, "resting": 60}
POLL_AFTER_QUIET = 300
_CODE = re.compile(r"^[a-z0-9_]{1,64}$")


def _workspace_id(entry: dict[str, Any]) -> str | None:
    workspace = entry.get("workspace")
    return str(workspace.get("id")) if isinstance(workspace, dict) and workspace.get("id") else None


def _visible(entry: dict[str, Any], workspaces: Collection[str] | None) -> bool:
    if workspaces is None:
        return True
    if entry.get("kind") in USER_WIDE_KINDS:
        return True
    return _workspace_id(entry) in workspaces


def _href(entry: dict[str, Any]) -> str | None:
    href = str((entry.get("link") or {}).get("href") or "")
    return href if href.startswith(("/", "https://", "http://")) else None


def _item(entry: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(entry.get("key") or ""), "kind": str(entry.get("kind") or ""),
            "title": str(entry.get("title") or "")[:MAX_TITLE], "url": _href(entry)}


def _run_item(run: dict[str, Any]) -> dict[str, Any]:
    session_id = run.get("session_id")
    return {"id": f"running:{run.get('id')}", "kind": "run", "title": str(run.get("title") or "")[:MAX_TITLE],
            "url": f"/chat?session_id={session_id}" if session_id else "/chat?area=work"}


def _newest(entries: list[dict[str, Any]], field: str) -> str | None:
    stamps = [str(entry[field]) for entry in entries if entry.get(field)]
    return max(stamps) if stamps else None


def _reason(entry: dict[str, Any]) -> str | None:
    code = str(entry.get("code") or "")
    return code if _CODE.match(code) else None


def pet_view(queue: dict[str, Any], *, workspaces: Collection[str] | None = None) -> dict[str, Any]:
    entries = [entry for entry in queue.get("items") or [] if _visible(entry, workspaces)]
    running = [run for run in queue.get("running") or [] if _visible(run, workspaces)]
    needs = [entry for entry in entries
             if entry.get("severity") == "action" or entry.get("kind") in THRESHOLD_KINDS]
    problems = [entry for entry in entries
                if entry.get("severity") == "warning" and entry.get("kind") not in THRESHOLD_KINDS]
    done = [entry for entry in entries if entry.get("severity") == "info"]
    working = [run for run in running if run.get("state") == "working"]

    reason = None
    if needs:
        state, items, since = "needs_you", [_item(entry) for entry in needs], _newest(needs, "created_at")
    elif problems:
        state, items, since = "problem", [_item(entry) for entry in problems], _newest(problems, "created_at")
        reason = _reason(problems[0])
    elif working:
        state, items, since = "working", [_run_item(run) for run in working], _newest(working, "updated_at")
    elif done:
        state, items, since = "done", [_item(entry) for entry in done], _newest(done, "created_at")
    else:
        state, items, since = "resting", [], None

    quiet = queue.get("quiet") or {}
    quiet = {"active": bool(quiet.get("active")), "until": quiet.get("until") if quiet.get("active") else None}
    headline = items[0]["title"] if items else ""
    if state == "working":  # the menu lists the runs; the headline counts them
        headline = f"{len(items)} run{'s' if len(items) != 1 else ''} working"
    view = {
        "v": VERSION, "state": state, "reason": reason, "since": since, "headline": headline,
        "count": len(items), "items": items[:MAX_ITEMS],
        "panel_url": PANEL_PATH, "poll_after_seconds": POLL_AFTER_QUIET if quiet["active"] else POLL_AFTER[state],
        "quiet": quiet,
    }
    return view


def view_etag(view: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f'"pet-{digest[:32]}"'


__all__ = ["MAX_ITEMS", "POLL_AFTER", "POLL_AFTER_QUIET", "VERSION", "pet_view", "view_etag"]
