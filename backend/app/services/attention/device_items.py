"""Attention entries for work on the person's Mac, so the person is notified.

Push notifications follow the attention queue (``mobile/push``). Besides approvals, questions and workflow runs, it
holds two kinds, so a person working in bypass mode, or talking to a running session over the live channel, is
notified too:

- **live** (``needs you``): a running Claude Code session wrote back to the person (``live_messages``, direction
  ``in``). One entry per conversation, for its newest unread answer; reading the conversation clears it
  (:func:`mark_live_read`), and the next answer notifies again;
- **turn** (``problem`` when it failed, ``done`` when it finished): a turn of the person's chat on their Mac ended
  (its ``turn_finished`` event). A stopped turn is not reported; "Done" clears an entry.

Both use the existing dismissals (an audit row per person and key, no new table) and look back
:data:`WITHIN`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, DeviceJobEvent, LiveMessage, Project, User, WorkflowRun, WorkflowRunSession
from ...time_utils import ensure_utc, utc_now
from .requests import action

WITHIN = timedelta(hours=24)
MAX_ITEMS = 30
FAILED = frozenset({"error", "failed", "timed_out"})


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _dismiss(key: str) -> dict[str, Any]:
    return action("dismiss", "Done", path="/api/v1/attention/dismiss", body={"key": key}, tone="primary")


async def live_entries(db: AsyncSession, user: User, dismissed: set[str]) -> list[dict[str, Any]]:
    since = (utc_now() - WITHIN).replace(tzinfo=None)
    rows = (await db.execute(select(LiveMessage).where(
        LiveMessage.owner_user_id == user.id, LiveMessage.direction == "in", LiveMessage.created_at >= since,
    ).order_by(LiveMessage.created_at.desc()).limit(200))).scalars().all()
    newest: dict[tuple[str, str], LiveMessage] = {}
    for message in rows:
        newest.setdefault((message.device_id, message.peer), message)
    entries = []
    for message in list(newest.values())[:MAX_ITEMS]:
        key = f"live:{message.id}"
        if key in dismissed:
            continue
        name = message.name or "A Claude Code session"
        entries.append({
            "key": key, "kind": "live", "id": message.id, "title": f"{name} answered you",
            "subtitle": "Running on your Mac", "text": message.text[:400], "created_at": _iso(message.created_at),
            "severity": "action", "workspace": None, "run": None, "work_item": None, "session_id": None,
            "live": {"device_id": message.device_id, "peer": message.peer},
            "link": {"href": "/m/", "label": "Open in Octryx Mobile"}, "actions": [_dismiss(key)],
        })
    return entries


async def turn_entries(db: AsyncSession, user: User, dismissed: set[str]) -> list[dict[str, Any]]:
    since = (utc_now() - WITHIN).replace(tzinfo=None)
    rows = (await db.execute(select(DeviceJobEvent, DeviceJob).join(DeviceJob, DeviceJob.id == DeviceJobEvent.job_id)
                             .where(DeviceJob.owner_user_id == user.id, DeviceJobEvent.type == "turn_finished",
                                    DeviceJobEvent.created_at >= since)
                             .order_by(DeviceJobEvent.created_at.desc()).limit(MAX_ITEMS))).all()
    names = {project_id: name for project_id, name in (await db.execute(select(Project.id, Project.name).where(
        Project.id.in_({job.workspace_id for _event, job in rows if job.workspace_id})))).all()} if rows else {}
    samples = await _sample_sessions(db, {job.session_id for _event, job in rows if job.session_id})
    entries = []
    for event, job in rows:
        body = event.body if isinstance(event.body, dict) else {}
        status = str(body.get("status") or "")
        if status == "stopped":
            continue
        key = f"turn:{job.id}:{str(body.get('turn_id') or event.seq)[:40]}"
        if key in dismissed:
            continue
        failed = status in FAILED
        folder = (job.folder or "").rstrip("/").rsplit("/", 1)[-1] or "your Mac"
        text = str(body.get("result_text") or body.get("error") or "")[:400]
        # A turn of an imported sample run never ran on this person's Mac.
        sample = job.session_id in samples
        where = "in the sample run" if sample else "on your Mac"
        entries.append({
            "key": key, "kind": "turn", "id": job.id, "sample": sample,
            "title": f"Failed {where} ({folder})" if failed else f"Finished {where} ({folder})",
            "subtitle": status or "finished", "text": text, "created_at": _iso(event.created_at),
            "severity": "warning" if failed else "info",
            "workspace": ({"id": job.workspace_id, "name": names[job.workspace_id]}
                          if job.workspace_id in names else None),
            "run": None, "work_item": None,
            "session_id": job.session_id,
            "link": {"href": f"/chat?session_id={job.session_id}", "label": "Open the chat"},
            "actions": [_dismiss(key)],
        })
    return entries


async def _sample_sessions(db: AsyncSession, session_ids: set[str]) -> set[str]:
    """The sessions of these that belong to an imported sample run (``views.is_sample``), in one query."""
    if not session_ids:
        return set()
    from ..workflow_runs.views import is_sample

    rows = (await db.execute(select(WorkflowRunSession.session_id, WorkflowRun).join(
        WorkflowRun, WorkflowRun.id == WorkflowRunSession.run_id).where(
        WorkflowRunSession.session_id.in_(sorted(session_ids))))).all()
    return {str(session_id) for session_id, run in rows if is_sample(run)}


async def mark_live_read(db: AsyncSession, user: User, *, device_id: str, peer: str) -> None:
    """The person read this conversation: its newest answer no longer needs them."""
    from .dismissals import dismiss, dismissed_keys

    newest = (await db.execute(select(LiveMessage.id).where(
        LiveMessage.owner_user_id == user.id, LiveMessage.device_id == device_id, LiveMessage.peer == peer,
        LiveMessage.direction == "in").order_by(LiveMessage.created_at.desc()).limit(1))).scalar_one_or_none()
    if newest and f"live:{newest}" not in await dismissed_keys(db, user):
        await dismiss(db, user, f"live:{newest}")


__all__ = ["live_entries", "mark_live_read", "turn_entries"]
