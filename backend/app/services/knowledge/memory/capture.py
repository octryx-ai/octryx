"""Capture: an explicit "remember this" becomes a human-stated memory item. A model never confirms anything."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_memory import (
    KnowledgeMemoryItem,
    MemoryAuthorClass,
    MemoryClass,
    MemoryScope,
    MemoryState,
)
from ....time_utils import utc_now
from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.scope import normalize_products
from .errors import MemoryRefusedError
from .text_guard import content_hash, normalize_memory_text
from .visibility import recallable

CLASSES_BY_SCOPE: dict[str, frozenset[str]] = {
    MemoryScope.USER.value: frozenset(
        {MemoryClass.PERSONAL.value, MemoryClass.LEARNING.value, MemoryClass.EPISODE_SUMMARY.value}
    ),
    MemoryScope.WORKSPACE.value: frozenset(
        {
            MemoryClass.DECISION.value,
            MemoryClass.CONVENTION.value,
            MemoryClass.LEARNING.value,
            MemoryClass.EPISODE_SUMMARY.value,
        }
    ),
}
DEFAULT_CLASS_BY_SCOPE = {MemoryScope.USER.value: MemoryClass.PERSONAL.value}
MAX_EXPIRY_DAYS = 3650
_MAX_REF_CHARS = 64


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    # Server-owned values of the run, never model arguments.
    user_id: str
    session_id: str | None = None
    turn_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CaptureResult:
    item: KnowledgeMemoryItem
    # "recorded" (new item), "already_known" (identical active item), "confirmed" (repetition confirmed it).
    outcome: str


def _ref(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and len(text) <= _MAX_REF_CHARS else None


def resolve_scope_and_class(scope: object, item_class: object) -> tuple[str, str]:
    scope_value = MemoryScope.USER.value if scope is None or scope == "" else scope
    if type(scope_value) is not str or scope_value not in CLASSES_BY_SCOPE:
        raise MemoryRefusedError("invalid_request")
    class_value = DEFAULT_CLASS_BY_SCOPE.get(scope_value) if item_class is None or item_class == "" else item_class
    if type(class_value) is not str or class_value not in CLASSES_BY_SCOPE[scope_value]:
        raise MemoryRefusedError("invalid_request")
    return scope_value, class_value


def resolve_product(scope: str, product: object) -> str | None:
    if product is None or product == "":
        return None
    if scope != MemoryScope.WORKSPACE.value:
        raise MemoryRefusedError("invalid_request")
    try:
        products = normalize_products(product)
    except InvalidEvidenceRequestError:
        products = ()
    if len(products) != 1:
        raise MemoryRefusedError("invalid_request")
    return products[0]


def resolve_expiry(expires_in_days: object):
    if expires_in_days is None:
        return None
    if type(expires_in_days) is not int or not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
        raise MemoryRefusedError("invalid_request")
    return utc_now() + timedelta(days=expires_in_days)


async def _existing_item(
    db: AsyncSession, *, project_id: str, digest: str, scope: str, owner: str | None, product: str | None,
    now: datetime,
) -> KnowledgeMemoryItem | None:
    return (
        await db.execute(
            select(KnowledgeMemoryItem)
            .where(
                KnowledgeMemoryItem.project_id == project_id,
                KnowledgeMemoryItem.content_hash == digest,
                KnowledgeMemoryItem.scope == scope,
                KnowledgeMemoryItem.owner_user_id.is_(None)
                if owner is None
                else KnowledgeMemoryItem.owner_user_id == owner,
                KnowledgeMemoryItem.product.is_(None)
                if product is None
                else KnowledgeMemoryItem.product == product,
                recallable(now),
            )
            .order_by(KnowledgeMemoryItem.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def remember(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    provenance: MemoryProvenance,
    text: object,
    scope: object = None,
    item_class: object = None,
    product: object = None,
    expires_in_days: object = None,
    author_class: MemoryAuthorClass = MemoryAuthorClass.HUMAN_STATED,
) -> CaptureResult:
    if author_class not in (MemoryAuthorClass.HUMAN_STATED, MemoryAuthorClass.MODEL_INFERRED):
        raise MemoryRefusedError("invalid_request")
    author_class = MemoryAuthorClass(author_class)
    scope_value, class_value = resolve_scope_and_class(scope, item_class)
    if scope_value == MemoryScope.WORKSPACE.value and not authorized.may_author:
        raise MemoryRefusedError("author_required")
    product_value = resolve_product(scope_value, product)
    expires_at = resolve_expiry(expires_in_days)
    body = normalize_memory_text(text)
    digest = content_hash(body)
    owner = provenance.user_id if scope_value == MemoryScope.USER.value else None
    now = utc_now()

    existing = await _existing_item(
        db, project_id=authorized.project_id, digest=digest, scope=scope_value, owner=owner, product=product_value,
        now=now,
    )
    if existing is not None:
        if existing.state == MemoryState.CONFIRMED.value or author_class != MemoryAuthorClass.HUMAN_STATED:
            return CaptureResult(item=existing, outcome="already_known")
        existing.state = MemoryState.CONFIRMED.value
        existing.state_changed_by = provenance.user_id
        existing.state_changed_at = now
        await db.flush()
        return CaptureResult(item=existing, outcome="confirmed")

    item = KnowledgeMemoryItem(
        project_id=authorized.project_id,
        scope=scope_value,
        owner_user_id=owner,
        product=product_value,
        item_class=class_value,
        author_class=author_class.value,
        # Stated by the user (or inferred from the turn), but not yet reviewed as a memory.
        state=MemoryState.OBSERVED.value,
        text=body,
        content_hash=digest,
        session_id=_ref(provenance.session_id),
        turn_ref=_ref(provenance.turn_ref),
        author_user_id=provenance.user_id,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(item)
    await db.flush()
    return CaptureResult(item=item, outcome="recorded")


__all__ = [
    "CLASSES_BY_SCOPE",
    "CaptureResult",
    "MemoryProvenance",
    "remember",
    "resolve_scope_and_class",
]
