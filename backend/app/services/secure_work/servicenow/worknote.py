"""Sending an analysis back to ServiceNow as a work note: prepared, and off by default.

Read-only towards ServiceNow unless write-back is explicitly enabled **and** configured on the connector:

- ``servicenow_worknote_mode``: ``off`` (default) | ``scripted_post`` | ``table_api``;
- ``servicenow_worknote_path``: the Scripted REST POST path for ``scripted_post`` (validated like paths).

There is never an automatic post. One explicit action posts one analysis note of a ServiceNow work item, with
the human confirmation pattern: without ``confirm`` the answer is ``needs_confirmation`` with the exact text and
target; only a confirmed repeat posts. What is posted is the analysis **summary** (the note's ``summary``, else
its first paragraph), never the raw evidence; a text the secret scan flags is refused. A note is posted once.

- ``table_api``: ``PATCH /api/now/table/<table>/<sys_id>`` with ``{"work_notes": text}``;
- ``scripted_post``: ``POST <path>`` with ``{"table", "sys_id", "number", "work_notes"}``.

Every post is audited (field names and counts, never the text). Failures are closed codes, never a body.

**Once, also under concurrency.** A confirmed post first claims the note: the work item row is locked
(``SELECT … FOR UPDATE``, the plan-write lock statement), the note re-read past the session's identity map and
re-checked, the ``worknote_posted_at`` marker written and committed, and only then is ServiceNow called. A
concurrent confirmation waits for the lock and then sees the marker (``servicenow_worknote_already_posted``).
A failed call releases the claim, so the post can be retried. A crash between claim and call leaves the note
marked as sent: the failure mode is a missing note, never a duplicate. (SQLite ignores ``FOR UPDATE``; there
the committed claim before the call is what a test proves.)
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import AuditLog, User, WorkItem
from ....time_utils import utc_now
from ...model_gateway.inbound.secret_scan import contains_secret
from ...oidc_client_credentials import OidcTokenError
from ...outbound_egress import CONNECTION_SERVICENOW, egress_transport
from ...servicenow_auth import resolve_servicenow_auth
from ...servicenow_scripted import (
    WORKNOTE_MODES,
    WORKNOTE_OFF,
    WORKNOTE_PATH_FIELD,
    WORKNOTE_TABLE_API,
    worknote_mode,
    worknote_problems,
)
from ..item_connection import work_item_connection_config
from ..plans.plan_write_lock import work_item_lock_statement
from .config import SOURCE_TYPE

CODE_DISABLED = "servicenow_worknote_disabled"
CODE_NOT_CONFIGURED = "servicenow_worknote_not_configured"
CODE_NOT_SERVICENOW = "servicenow_worknote_not_a_servicenow_item"
CODE_NO_ANALYSIS = "servicenow_worknote_no_analysis_note"
CODE_ALREADY_POSTED = "servicenow_worknote_already_posted"
CODE_SECRET = "servicenow_worknote_secret_detected"
CODE_FAILED = "servicenow_worknote_failed"
POST_AUDIT_ACTION = "secure_work.servicenow_worknote.posted"
DISABLED_HINT = "Work notes to ServiceNow are off; an admin enables servicenow_worknote_mode on the connector."
MAX_WORKNOTE_CHARS = 4000


def _refuse(status: int, state: str, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"state": state, "code": code, "message": message})


def _analysis_note(item: WorkItem, note_at: str | None) -> tuple[int, dict[str, Any]] | None:
    notes = (item.source_fields_json or {}).get("platform_notes") or []
    candidates = [(index, note) for index, note in enumerate(notes)
                  if isinstance(note, dict) and note.get("kind") == "analysis"
                  and (note_at is None or note.get("at") == note_at)]
    return candidates[-1] if candidates else None


def worknote_text(note: dict[str, Any]) -> str:
    """The analysis summary: the note's ``summary``, else the first paragraph of its text; bounded."""
    summary = note.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = str(note.get("note") or "").strip().split("\n\n", 1)[0]
    return summary.strip()[:MAX_WORKNOTE_CHARS]


async def send_worknote(
    db: AsyncSession, *, item: WorkItem, user: User, note_at: str | None, confirm: bool
) -> dict[str, Any]:
    """Preview (no ``confirm``) or post one analysis summary as a work note; raises coded refusals."""
    if item.source_type != SOURCE_TYPE:
        raise _refuse(409, "denied", CODE_NOT_SERVICENOW, "Only a ServiceNow work item has a ServiceNow work note.")
    config, refused = await work_item_connection_config(db, item, SOURCE_TYPE)
    if refused:
        raise _refuse(409, "needs_configuration", refused, "No connection of this Workspace serves the record's table.")
    mode = worknote_mode(config)
    if mode == WORKNOTE_OFF:
        raise _refuse(409, "disabled", CODE_DISABLED, DISABLED_HINT)
    if mode not in WORKNOTE_MODES or worknote_problems(config):
        raise _refuse(409, "needs_configuration", CODE_NOT_CONFIGURED, "The work-note settings are incomplete.")
    found = _analysis_note(item, note_at)
    if found is None:
        raise _refuse(404, "not_found", CODE_NO_ANALYSIS, "The work item has no such analysis note.")
    note = found[1]
    if note.get("worknote_posted_at"):
        raise _refuse(409, "denied", CODE_ALREADY_POSTED, "This analysis was already sent as a work note.")
    text = worknote_text(note)
    if not text:
        raise _refuse(404, "not_found", CODE_NO_ANALYSIS, "The analysis note has no summary.")
    if contains_secret(text):
        raise _refuse(422, "denied", CODE_SECRET, "The summary contains secret material; it is never sent.")
    fields = dict((item.source_fields_json or {}).get("servicenow") or {})
    target = {"mode": mode, "table": fields.get("table") or item.issue_type, "number": item.source_key}
    if not confirm:
        return {"state": "needs_confirmation", "preview": {**target, "text": text}}
    index = await _claim(db, item, note, user)
    try:
        await _post(config, mode, target, str(fields.get("sys_id") or item.source_id or ""), text)
    except HTTPException:
        await _release(db, item, index)
        raise
    db.add(AuditLog(user_id=user.id, action=POST_AUDIT_ACTION, resource_type="work_item", resource_id=item.id,
                    details={"mode": mode, "table": target["table"], "chars": len(text)}))
    await db.flush()
    return {"state": "posted", **target}


async def _set_note(db: AsyncSession, item: WorkItem, index: int, note: dict[str, Any]) -> None:
    notes = list(item.source_fields_json["platform_notes"])
    notes[index] = note
    item.source_fields_json = {**item.source_fields_json, "platform_notes": notes}
    flag_modified(item, "source_fields_json")
    await db.commit()


async def _claim(db: AsyncSession, item: WorkItem, note: dict[str, Any], user: User) -> int:
    """Under the row lock, on the stored note: refuse a sent one, else mark it sent and commit; its index."""
    locked = (await db.execute(work_item_lock_statement(item.id))).scalar_one()
    current = _analysis_note(locked, note.get("at"))
    if current is None or current[1].get("worknote_posted_at"):
        await db.rollback()
        raise _refuse(409, "denied", CODE_ALREADY_POSTED, "This analysis was already sent as a work note.")
    index, stored = current
    await _set_note(db, locked, index, {**stored, "worknote_posted_at": utc_now().isoformat(),
                                        "worknote_posted_by": user.username})
    return index


async def _release(db: AsyncSession, item: WorkItem, index: int) -> None:
    """Remove the claim of a post that failed, under the same lock."""
    locked = (await db.execute(work_item_lock_statement(item.id))).scalar_one()
    note = dict(locked.source_fields_json["platform_notes"][index])
    note.pop("worknote_posted_at", None)
    note.pop("worknote_posted_by", None)
    await _set_note(db, locked, index, note)


async def _post(config: dict[str, Any], mode: str, target: dict[str, Any], sys_id: str, text: str) -> None:
    base_url = str(config.get("servicenow_url") or "").strip().rstrip("/")
    credential = resolve_servicenow_auth(config)
    if not base_url or credential is None or not sys_id.isalnum():
        raise _refuse(409, "needs_configuration", CODE_NOT_CONFIGURED, "The ServiceNow connection is incomplete.")
    headers = {"Accept": "application/json", **credential.headers()}
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, transport=egress_transport(CONNECTION_SERVICENOW),
            auth=credential.http_auth(),
        ) as client:
            if mode == WORKNOTE_TABLE_API:
                response = await client.patch(f"{base_url}/api/now/table/{target['table']}/{sys_id}",
                                              json={"work_notes": text}, headers=headers)
            else:
                body = {"table": target["table"], "sys_id": sys_id, "number": target["number"], "work_notes": text}
                response = await client.post(f"{base_url}{config[WORKNOTE_PATH_FIELD]}", json=body, headers=headers)
    except (OidcTokenError, httpx.HTTPError):
        raise _refuse(502, "failed", CODE_FAILED, "ServiceNow could not be reached.") from None
    if not 200 <= response.status_code < 300:
        raise _refuse(502, "failed", CODE_FAILED, f"ServiceNow answered HTTP {response.status_code}.")


__all__ = ["CODE_DISABLED", "send_worknote", "worknote_text"]
