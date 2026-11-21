"""A Jira Work item moves along a workflow run's lifecycle by Jira's status category when no write-back is defined.

Without this, a chain can run end to end (spec-writing for the epic, epic-delivery with a pull request per story,
all done) while its Jira items stay in Intake on the board and "To Do" in Jira: a Workspace without a write-back
definition makes ``auto_transition_work_item`` skip every move (``no_workflow_in_scope``), and only platform items
move. Defaults must work without
configuration, so a run's own lifecycle points use this default mapping instead:

- ``development`` (an epic while its stories run) and ``review`` (a story whose pull request is open) both lie in
  Jira's ``indeterminate`` category ("In Progress"). The transition is chosen from what Jira really offers for the
  issue: a target status whose name says ``review`` for review, else one that says ``progress``; else the only
  transition into that category. Several without a fitting name, or none, is no move in Jira (never a guess).
- ``done`` is never set here: the person merges, and Jira's own done status then closes the item at the next sync.
- The issue must lie in the connection's ``jira_allowed_projects`` (the same check as every write-back); nothing is
  sent otherwise.

The board follows the run either way (a state event, source ``platform_lifecycle``, which the Jira sync never
regresses); the Jira outcome is on the event and returned. A configured write-back definition always wins: this
applies only when none is in scope.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport

from ....models import User, WorkItem, WorkItemStateEvent
from ....time_utils import utc_now
from .jira_scope import writable_issue
from .jira_state_sync import _jira_access, _target_category

logger = logging.getLogger(__name__)

MODE = "default_status_category"
SOURCE = "platform_lifecycle"
CATEGORY = "indeterminate"
#: Work state -> name hints of the Jira target status, in order of preference (all in ``indeterminate``).
TARGETS: dict[str, tuple[str, ...]] = {"development": ("progress", "develop"), "review": ("review", "progress")}
_TERMINAL = frozenset({"done", "completed", "cancelled", "canceled", "rejected", "superseded"})


def pick_transition(available: list[dict[str, Any]], to_state: str, current_status: str = "") -> dict[str, Any] | None:
    """The transition Jira offers into the default target of ``to_state``; ``None`` when none fits clearly."""
    current = current_status.strip().lower()
    candidates = [entry for entry in available if _target_category(entry) == CATEGORY
                  and str((entry.get("to") or {}).get("name") or "").strip().lower() != current]
    for hint in TARGETS.get(to_state, ()):
        named = [entry for entry in candidates if hint in str((entry.get("to") or {}).get("name") or "").lower()]
        if named:
            return named[0]
    return candidates[0] if len(candidates) == 1 else None


async def _write_to_jira(db: AsyncSession, item: WorkItem, to_state: str) -> dict[str, Any]:
    """``{status: executed|unchanged|not_offered|scope_not_allowed|not_configured|failed, ...}``; never raises."""
    base_url, authorization, _cloud, allowed, http_auth = await _jira_access(item, db)
    try:
        writable_issue(item.source_key, allowed)
    except HTTPException:
        return {"status": "scope_not_allowed"}
    if not base_url or not (authorization or http_auth):
        return {"status": "not_configured"}
    headers = {**authorization, "Accept": "application/json", "Content-Type": "application/json"}
    url = f"{base_url}/rest/api/2/issue/{item.source_key}/transitions"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, auth=http_auth,
                                     transport=egress_transport(CONNECTION_JIRA)) as client:
            listing = await client.get(url, headers=headers)
            if listing.status_code >= 400:
                return {"status": "failed", "detail": f"transitions lookup {listing.status_code}"}
            available = [entry for entry in listing.json().get("transitions") or [] if isinstance(entry, dict)]
            matched = pick_transition(available, to_state, str(item.source_status or ""))
            if matched is None:
                return {"status": "not_offered", "offered": [
                    f"{entry.get('name')} -> {(entry.get('to') or {}).get('name')}" for entry in available]}
            response = await client.post(url, headers=headers, json={"transition": {"id": str(matched.get("id"))}})
    except httpx.HTTPError as error:
        return {"status": "failed", "detail": type(error).__name__}
    if response.status_code >= 400:
        return {"status": "failed", "detail": f"transition {response.status_code}"}
    resulting = str((matched.get("to") or {}).get("name") or "").strip()
    if resulting:
        item.source_status = resulting[:120]
    return {"status": "executed", "transition_name": matched.get("name"), "resulting_status": resulting}


async def move_by_status_category(db: AsyncSession, item: WorkItem, *, current_user: User, to_state: str,
                                  reason: str) -> dict[str, Any]:
    """Move a Jira item without a write-back definition: Jira by status category, then the board."""
    previous = str(item.work_state or "").strip() or "intake"
    if to_state not in TARGETS or str(item.source_type or "") != "jira":
        return {"status": "skipped", "reason": "no_workflow_in_scope", "to_state": to_state}
    if previous in _TERMINAL:
        return {"status": "skipped", "reason": "terminal_state", "to_state": to_state}
    if previous == to_state:
        return {"status": "unchanged", "to_state": to_state}
    jira = await _write_to_jira(db, item, to_state)
    item.work_state = to_state
    item.updated_at = utc_now()
    db.add(WorkItemStateEvent(
        work_item_id=item.id, from_state=previous, to_state=to_state, actor_id=current_user.id, reason=reason,
        source=SOURCE, dry_run=False, conflict_json={},
        jira_sync_preview_json={"mode": MODE, "will_mutate_jira": jira["status"] == "executed", "execution": jira},
    ))
    logger.info("work_item_auto_transition_applied source_key=%s state=%s mode=%s jira=%s", item.source_key,
                to_state, MODE, jira["status"])
    return {"status": "applied", "from_state": previous, "to_state": to_state, "mode": MODE, "jira": jira}


__all__ = ["MODE", "TARGETS", "move_by_status_category", "pick_transition"]
