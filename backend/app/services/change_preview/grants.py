"""Request fingerprints, the central gate's per-call marks and consuming a session's approval grants."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session


def build_change_request_fingerprint(tool_name: str, payload: Any) -> str:
    try:
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        normalized = str(payload)
    return hashlib.sha256(f"{tool_name}:{normalized}".encode()).hexdigest()


def enforced_approval_mark(tool_name: str, payload: Any) -> str:
    return "tool:" + build_change_request_fingerprint(tool_name, payload)


def record_enforced_approval_mark(context: Any, tool_name: str, payload: Any) -> None:
    marks = getattr(context, "enforced_approval_fingerprints", None)
    if isinstance(marks, set):
        marks.add(enforced_approval_mark(tool_name, payload))


def record_approval_ref(context: Any, tool_name: str, payload: Any, **ref: str | None) -> None:
    """Remember what admitted this call (``approval_id`` or ``write_plan_id``) for the tool's own audit row."""
    refs = getattr(context, "approval_refs", None)
    values = {key: str(value) for key, value in ref.items() if value}
    if isinstance(refs, dict) and values:
        refs[enforced_approval_mark(tool_name, payload)] = values


def approval_ref_for(context: Any, tool_name: str, payload: Any) -> dict[str, str]:
    """What admitted this call, once (empty when nothing had to: a read, or no rule asked)."""
    refs = getattr(context, "approval_refs", None)
    if not isinstance(refs, dict):
        return {}
    return refs.pop(enforced_approval_mark(tool_name, payload), {}) or {}


def consume_enforced_approval_mark(context: Any, tool_name: str, payload: Any) -> bool:
    """Consume the central gate's mark for exactly this call, once (server-owned; nothing model-supplied)."""
    marks = getattr(context, "enforced_approval_fingerprints", None)
    mark = enforced_approval_mark(tool_name, payload)
    if not isinstance(marks, set) or mark not in marks:
        return False
    marks.discard(mark)
    return True


async def consume_change_preview_grant(
    db: AsyncSession | None,
    *,
    session_id: str | None,
    tool_name: str,
    payload: Any,
    context: Any = None,
    mark_payload: Any = None,
    consumed: dict[str, Any] | None = None,
) -> bool:
    """Consume one matching approval grant of the session; ``True`` when one was consumed."""
    if consume_enforced_approval_mark(context, tool_name, payload if mark_payload is None else mark_payload):
        return True
    if db is None or not session_id:
        return False
    session = await db.get(Session, session_id)
    if session is None:
        return False
    metadata = dict(session.metadata_ or {})
    grants = list(metadata.get("approval_grants") or [])
    fingerprint = build_change_request_fingerprint(tool_name, payload)
    remaining: list[dict[str, Any]] = []
    matched = False
    for grant in grants:
        if (
            not matched
            and str(grant.get("tool_name") or "").strip() == tool_name
            and str(grant.get("request_fingerprint") or "").strip() == fingerprint
        ):
            matched = True
            if consumed is not None:
                consumed["approval_id"] = grant.get("approval_id")
            continue
        remaining.append(grant)
    if matched:
        metadata["approval_grants"] = remaining
        session.metadata_ = metadata
        await db.flush()
    return matched
