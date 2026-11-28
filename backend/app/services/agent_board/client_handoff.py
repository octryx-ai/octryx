"""The server side of the client handoff routine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, User, WorkItem, WorkItemClaim, WorkItemHandoffAttachment
from ...time_utils import utc_now
from ..agent_gateway.handoff_policy_keys import MODE_AUTO
from ..agent_gateway.identity import GatewayIdentity
from ..project.service import get_project_access_details
from .claim_values import KIND_GATEWAY_SESSION
from .claims import live_claim
from .handoffs import AUTHOR_AGENT, AUTHOR_HUMAN, SERVER_KEYS, latest_handoff, validate_sections, write_handoff
from .messages import Author
from .takeover_listing import takeover_views
from .takeovers import request_takeover

MAX_NOTE_CHARS = 4000
MAX_FACTS = 100


def _hash(session_key: str) -> str:
    from ..agent_gateway.presence import session_key_hash

    return session_key_hash(session_key)


async def item_by_key(db: AsyncSession, project_id: str, key: str) -> WorkItem | None:
    statement = select(WorkItem).where(
        WorkItem.project_id == project_id, or_(WorkItem.id == key, WorkItem.source_key == key)
    )
    return (await db.execute(statement.limit(1))).scalar_one_or_none()


async def _held(db: AsyncSession, project_id: str, *, user_id: str | None = None,
                ref_hash: str | None = None) -> list[WorkItem]:
    statement = (
        select(WorkItem)
        .join(WorkItemClaim, WorkItemClaim.work_item_id == WorkItem.id)
        .where(WorkItemClaim.project_id == project_id, WorkItemClaim.released_at.is_(None),
               WorkItemClaim.lease_until > utc_now())
    )
    if user_id is not None:
        statement = statement.where(WorkItemClaim.holder_user_id == user_id)
    if ref_hash is not None:
        statement = statement.where(WorkItemClaim.holder_kind == KIND_GATEWAY_SESSION,
                                    WorkItemClaim.holder_ref_hash == ref_hash)
    return list((await db.execute(statement.order_by(WorkItem.source_key))).scalars().all())


async def resolve_items(db: AsyncSession, identity: GatewayIdentity, *, key: str, all_items: bool) -> list[WorkItem]:
    project_id = identity.workspace_id
    if key:
        item = await item_by_key(db, project_id, key)
        if item is None:
            raise HTTPException(status_code=404, detail={"code": "work_item_not_found"})
        return [item]
    if all_items:
        return await _held(db, project_id, user_id=identity.user.id)
    if identity.work_item_key:
        item = await item_by_key(db, project_id, identity.work_item_key)
        if item is not None:
            return [item]
    held = await _held(db, project_id, ref_hash=_hash(identity.session_key))
    if held:
        return held
    from ..secure_work.platform_items import create_platform_work_item

    name = identity.user.display_name or identity.user.username
    title = f"Handoff from {name} {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    return [await create_platform_work_item(db, current_user=identity.user, project_id=project_id, title=title)]


def item_view(item: WorkItem) -> dict[str, str]:
    return {"id": item.id, "key": item.source_key, "title": item.title}


def _strings(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FACTS or not all(isinstance(entry, str) for entry in value):
        raise HTTPException(status_code=422, detail={"code": "handoff_invalid", "field": field})
    return value


async def _member(db: AsyncSession, project_id: str, reference: str) -> User:
    user = (
        await db.execute(select(User).where(or_(User.id == reference, User.username == reference,
                                                User.email == reference)).limit(1))
    ).scalar_one_or_none()
    if user is None or project_id not in {str(entry["id"]) for entry in await get_project_access_details(user.id, db)}:
        raise HTTPException(status_code=422, detail={"code": "to_user_not_member"})
    return user


async def commit_handoff(db: AsyncSession, identity: GatewayIdentity, payload: dict[str, Any]) -> dict[str, Any]:
    item = await item_by_key(db, identity.workspace_id, str(payload.get("work_item_id") or ""))
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "work_item_not_found"})
    claim = await live_claim(db, item.id)
    if claim is not None and claim.holder_user_id != identity.user.id:
        raise HTTPException(status_code=409, detail={"code": "claimed_by_other"})
    repo = payload.get("repo") if isinstance(payload.get("repo"), dict) else {}
    bundle_id = repo.get("bundle_id")
    if bundle_id is not None:
        attachment = await db.get(WorkItemHandoffAttachment, str(bundle_id))
        if attachment is None or attachment.work_item_id != item.id:
            raise HTTPException(status_code=422, detail={"code": "bundle_not_found"})
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    note = payload.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
        raise HTTPException(status_code=422, detail={"code": "handoff_invalid", "field": "note"})
    previous = await latest_handoff(db, item.id)
    sections = {key: value for key, value in dict(previous.sections or {}).items() if key not in SERVER_KEYS} \
        if previous is not None else {}
    sections["repo"] = {name: repo[name] for name in ("url", "branch", "base_commit", "wip_commit", "bundle_id")
                        if repo.get(name) is not None}
    for field in ("last_commits", "changed_files", "excluded_files"):
        sections[field] = _strings(git.get(field), f"git.{field}")
    if note:
        sections["notes"] = note
    sections = validate_sections(sections)
    own_session = claim is not None and claim.holder_ref_hash == _hash(identity.session_key)
    handoff = await write_handoff(
        db, item=item, sections=sections, author_kind=AUTHOR_AGENT if own_session else AUTHOR_HUMAN,
        author_user_id=identity.user.id, author_agent_hash=claim.holder_ref_hash if own_session else None,
    )
    takeover = await _takeover(db, identity, item, claim, payload.get("to_user"), note)
    await _clear_requested(db, identity.session_key)
    return {
        "state": "handed_over",
        "work_item": item_view(item),
        "handoff": {"id": handoff.id, "version": handoff.version},
        "takeover": (await takeover_views(db, [takeover]))[0] if takeover is not None else None,
    }


async def _clear_requested(db: AsyncSession, session_key: str) -> None:
    presence = (
        await db.execute(select(AgentPresence).where(AgentPresence.session_key == session_key))
    ).scalar_one_or_none()
    if presence is not None and presence.handoff_requested_at is not None:
        presence.handoff_requested_at = None
        await db.flush()


async def request_hand_over_now(db: AsyncSession, claim: WorkItemClaim) -> bool:
    from .automation import post_automatic_request

    item = await db.get(WorkItem, claim.work_item_id)
    await post_automatic_request(db, claim, item)
    if claim.holder_kind != KIND_GATEWAY_SESSION:
        return False
    for presence in (await db.execute(select(AgentPresence).where(
            AgentPresence.project_id == claim.project_id, AgentPresence.stopped_at.is_(None)))).scalars().all():
        if _hash(presence.session_key) == claim.holder_ref_hash:
            presence.handoff_requested_at = utc_now()
            await db.flush()
            return True
    return False


async def _takeover(db: AsyncSession, identity: GatewayIdentity, item: WorkItem, claim: WorkItemClaim | None,
                    to_user: Any, note: str | None) -> Any:
    reason = (note or "").strip() or "Handoff from the client."
    if to_user:
        receiver = await _member(db, identity.workspace_id, str(to_user))
        return await request_takeover(
            db, item=item, to_user_id=receiver.id, to_agent_hash=None, to_agent_kind=None, reason=reason,
            author=Author(AUTHOR_HUMAN, identity.user.id), message_to_user_id=receiver.id, require_claim=False,
        )
    if claim is None:
        return None
    from .auto_takeover import workspace_handoff_policy
    from .automation import make_offer, post_automatic_request

    # The holder handed over itself: that satisfies auto condition 1 when an agent later requests the item.
    claim.handed_off_at = utc_now()
    policy = await workspace_handoff_policy(db, identity.workspace_id)
    offered = await make_offer(db, claim, policy) if policy.mode == MODE_AUTO else None
    await post_automatic_request(db, claim, item, to_agent_hash=offered)
    return None  # a request plus an offer, never an assignment


__all__ = ["commit_handoff", "item_by_key", "item_view", "request_hand_over_now", "resolve_items"]
