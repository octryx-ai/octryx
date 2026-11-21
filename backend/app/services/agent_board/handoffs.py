"""Structured, versioned Work Item handoffs.

- **Sections** (all optional): strings ``goal``, ``acceptance``, ``rules``, ``state``, ``notes``; lists of strings
  ``last_commits``, ``next_steps``, ``open_decisions``, ``pitfalls``, ``changed_files``, ``excluded_files``; objects
  ``repo {url, branch, worktree, base_commit, wip_commit, bundle_id}`` (the work state that travels)
  and ``commands {build, test, deploy, other[]}``. ``linked_sessions`` is filled by the server, never the client.
  Each string is at most 4 KB, the whole document at most 32 KB (UTF-8 JSON).
- **Refusals:** an unknown key or shape is 422 ``handoff_invalid`` naming the field; any secret (the gateway's
  secret scan) is 422 ``secret_detected`` and URL userinfo (``user:pass@host``, the project config detector, per
  word) is 422 ``url_userinfo_refused``. A refused value is never echoed.
- **Writes** append version ``n+1``; a racing writer of the same version loses on ``uq_work_item_handoff_version``
  and gets 409 ``handoff_version_conflict``. Who may write is the caller's rule (``mcp_work_handoff_tools``).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Session, WorkItem, WorkItemHandoff
from ...time_utils import utc_now
from ..model_gateway.inbound.secret_scan import contains_secret
from .claim_values import iso
from .envelope import user_refs

TEXT_KEYS = ("goal", "acceptance", "rules", "state", "notes")
LIST_KEYS = ("last_commits", "next_steps", "open_decisions", "pitfalls", "changed_files", "excluded_files")
OBJECT_KEYS = {
    "repo": ("url", "branch", "worktree", "base_commit", "wip_commit", "bundle_id"),
    "commands": ("build", "test", "deploy", "other"),
}
LIST_FIELDS = {"commands": ("other",)}
SERVER_KEYS = ("linked_sessions",)
MAX_STRING_BYTES = 4 * 1024
MAX_DOCUMENT_BYTES = 32 * 1024
MAX_LIST_ITEMS = 100
MAX_LINKED_SESSIONS = 20

CODE_INVALID = "handoff_invalid"
_SAFE_KEY = re.compile(r"[a-z_]{1,32}")
CODE_SECRET = "secret_detected"
CODE_USERINFO = "url_userinfo_refused"
CODE_VERSION_CONFLICT = "handoff_version_conflict"
AUTHOR_AGENT = "agent"
AUTHOR_HUMAN = "human"


def _refuse(code: str, field: str | None = None, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, **({"field": field} if field else {})})


def _carries_userinfo(text: str) -> bool:
    from ..tool_config.url_userinfo import carries_userinfo as detector

    return any(detector(word) for word in text.split())


def _string(value: Any, field: str) -> str:
    if type(value) is not str or len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise _refuse(CODE_INVALID, field)
    if contains_secret(value):
        raise _refuse(CODE_SECRET, field)
    if _carries_userinfo(value):
        raise _refuse(CODE_USERINFO, field)
    return value


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise _refuse(CODE_INVALID, field)
    return [_string(entry, f"{field}[{index}]") for index, entry in enumerate(value)]


def validate_sections(value: Any) -> dict[str, Any]:
    """The normalized document, or a coded 422. ``linked_sessions`` from a client is refused."""
    if not isinstance(value, dict):
        raise _refuse(CODE_INVALID, "sections")
    allowed = set(TEXT_KEYS) | set(LIST_KEYS) | set(OBJECT_KEYS)
    unknown = sorted(str(key) for key in set(value) - allowed)
    if unknown:
        # A key is echoed only when it looks like a key; anything else (a secret, say) never is.
        raise _refuse(CODE_INVALID, unknown[0] if _SAFE_KEY.fullmatch(unknown[0]) else "sections")
    sections: dict[str, Any] = {}
    for key, raw in value.items():
        if raw is None:
            continue
        if key in TEXT_KEYS:
            sections[key] = _string(raw, key)
        elif key in LIST_KEYS:
            sections[key] = _strings(raw, key)
        else:
            if not isinstance(raw, dict) or set(raw) - set(OBJECT_KEYS[key]):
                raise _refuse(CODE_INVALID, key)
            sections[key] = {
                name: (_strings(entry, f"{key}.{name}") if name in LIST_FIELDS.get(key, ()) else
                       _string(entry, f"{key}.{name}"))
                for name, entry in raw.items() if entry is not None
            }
    if len(json.dumps(sections, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise _refuse(CODE_INVALID, "sections")
    return sections


async def latest_handoff(db: AsyncSession, work_item_id: str) -> WorkItemHandoff | None:
    statement = (
        select(WorkItemHandoff)
        .where(WorkItemHandoff.work_item_id == work_item_id)
        .order_by(WorkItemHandoff.version.desc())
        .limit(1)
    )
    return (await db.execute(statement)).scalar_one_or_none()


async def _linked_sessions(db: AsyncSession, item: WorkItem) -> list[str]:
    """Shadow sessions of the agent sessions registered for this item (by key or id), newest first."""
    keys = [value for value in (item.source_key, item.id) if value]
    rows = (
        await db.execute(
            select(AgentPresence.session_id)
            .join(Session, Session.id == AgentPresence.session_id)
            .where(AgentPresence.project_id == item.project_id, AgentPresence.work_item_key.in_(keys))
            .order_by(AgentPresence.registered_at.desc())
            .limit(MAX_LINKED_SESSIONS)
        )
    ).scalars().all()
    return [str(value) for value in rows if value]


async def write_handoff(
    db: AsyncSession, *, item: WorkItem, sections: dict[str, Any], author_kind: str, author_user_id: str,
    author_agent_hash: str | None,
) -> WorkItemHandoff:
    """Append the next version. ``sections`` must come from :func:`validate_sections`. Flushes."""
    last = (
        await db.execute(select(func.max(WorkItemHandoff.version)).where(WorkItemHandoff.work_item_id == item.id))
    ).scalar_one()
    document = {**sections, "linked_sessions": await _linked_sessions(db, item)}
    handoff = WorkItemHandoff(
        id=str(uuid.uuid4()),
        project_id=item.project_id,
        work_item_id=item.id,
        version=int(last or 0) + 1,
        author_kind=author_kind,
        author_user_id=author_user_id,
        author_agent_hash=author_agent_hash,
        created_at=utc_now(),
        sections=document,
    )
    try:
        async with db.begin_nested():
            db.add(handoff)
            await db.flush()
    except IntegrityError:
        raise _refuse(CODE_VERSION_CONFLICT, status=409) from None
    return handoff


async def handoff_views(db: AsyncSession, rows: list[WorkItemHandoff]) -> list[dict[str, Any]]:
    """``{id, work_item, version, author, created_at, sections}`` per handoff."""
    if not rows:
        return []
    item_ids = sorted({row.work_item_id for row in rows})
    items = {
        item.id: item
        for item in (await db.execute(select(WorkItem).where(WorkItem.id.in_(item_ids)))).scalars().all()
    }
    users = await user_refs(db, [row.author_user_id for row in rows])
    views = []
    for row in rows:
        item = items.get(row.work_item_id)
        views.append(
            {
                "id": row.id,
                "work_item": {"id": item.id, "key": item.source_key, "title": item.title} if item else None,
                "version": row.version,
                "author": {"type": row.author_kind, "user": users.get(row.author_user_id),
                           "agent_hash": row.author_agent_hash},
                "created_at": iso(row.created_at),
                "sections": dict(row.sections or {}),
            }
        )
    return views


async def list_handoffs(db: AsyncSession, *, project_id: str, work_item_id: str | None) -> list[WorkItemHandoff]:
    """Every version of one item (newest first), or the latest version of each item in the Workspace."""
    statement = select(WorkItemHandoff).where(WorkItemHandoff.project_id == project_id)
    if work_item_id:
        statement = statement.where(WorkItemHandoff.work_item_id == work_item_id)
        return list((await db.execute(statement.order_by(WorkItemHandoff.version.desc()))).scalars().all())
    latest = (
        select(WorkItemHandoff.work_item_id, func.max(WorkItemHandoff.version).label("version"))
        .where(WorkItemHandoff.project_id == project_id)
        .group_by(WorkItemHandoff.work_item_id)
        .subquery()
    )
    statement = statement.join(
        latest,
        (latest.c.work_item_id == WorkItemHandoff.work_item_id) & (latest.c.version == WorkItemHandoff.version),
    ).order_by(WorkItemHandoff.created_at.desc())
    return list((await db.execute(statement)).scalars().all())


__all__ = [
    "AUTHOR_AGENT",
    "AUTHOR_HUMAN",
    "CODE_SECRET",
    "CODE_USERINFO",
    "handoff_views",
    "latest_handoff",
    "list_handoffs",
    "validate_sections",
    "write_handoff",
]
