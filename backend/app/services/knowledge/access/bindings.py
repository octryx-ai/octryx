"""Workspace read bindings and the Knowledge scope of one read.

A read runs against a :class:`KnowledgeScope`: the caller's own Workspace first, then every Workspace
it holds an active binding to (``models/project/knowledge_bindings.py``). The scope is resolved from
the ledger on every read, never from the prompt or a tool argument. It is bounded and closed:

- at most :data:`MAX_BINDINGS` sources, in the order they were bound; bindings are not transitive;
- a source is read with ``on_behalf_of`` set to the reader, so every remote call (embedding, rerank)
  is admitted for the reader's data policy, and the read can never author;
- a source's products bound the read: the requested products are intersected with the binding's,
  and a source whose intersection is empty is not queried;
- a source whose data classification now ranks above the reader's is skipped with a fixed reason,
  as is one that cannot be classified; the binding stays, so the admin can see why it is inert.

Creating a binding needs the authoring role in *both* Workspaces (a platform admin has it
everywhere); either side may revoke it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, User
from ....models.project.knowledge_bindings import (
    BINDING_STATE_ACTIVE,
    BINDING_STATE_REVOKED,
    KnowledgeWorkspaceBinding,
)
from ....time_utils import utc_now
from ...data_classification.effect_rules import knowledge_sharing_off
from ...data_classification.levels import level_registry
from ...model_gateway.data_policy.classification import classification_rank
from ...model_gateway.data_policy.source import resolve_workspace_data_classification
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.scope import normalize_products
from .authorization import BOUND_READER_ROLE, AuthorizedWorkspace, authorize_workspace, parse_workspace_id

MAX_BINDINGS = 5
MAX_REASON_CHARS = 500

SKIP_CLASSIFICATION_ABOVE_READER = "classification_above_reader"
SKIP_CLASSIFICATION_UNRESOLVED = "classification_unresolved"
# An added classification rule: the source's level does not share its Knowledge.
SKIP_CLASSIFICATION_SHARING_OFF = "classification_sharing_off"


class BindingRefusedError(Exception):
    """A binding request that the rules refuse; ``reason`` is a fixed token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class BoundSource:
    """One Workspace the reader may read through a binding."""

    authorized: AuthorizedWorkspace
    name: str
    products: tuple[str, ...]

    def products_for(self, requested: tuple[str, ...]) -> tuple[str, ...] | None:
        """The product filter for this source, or ``None`` when the request lies outside the binding."""
        if not self.products:
            return requested
        if not requested:
            return self.products
        narrowed = tuple(product for product in requested if product in self.products)
        return narrowed or None


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    primary: AuthorizedWorkspace
    primary_name: str
    sources: tuple[BoundSource, ...] = ()
    # Bound Workspaces that were not read, with the fixed reason.
    skipped: dict[str, str] = field(default_factory=dict)

    def name_of(self, project_id: str) -> str:
        if project_id == self.primary.project_id:
            return self.primary_name
        return next((source.name for source in self.sources if source.authorized.project_id == project_id), "")

    def source_for(self, project_id: str) -> BoundSource | None:
        return next((source for source in self.sources if source.authorized.project_id == project_id), None)


async def _classification_rank(db: AsyncSession, project_id: str) -> int | None:
    classification = await resolve_workspace_data_classification(db, project_id=project_id)
    return classification_rank(classification.classification) if classification.resolved else None


async def _compatibility(db: AsyncSession, *, reader: str, source: str) -> str | None:
    """``None`` when ``source`` may flow into ``reader``; else the fixed reason it may not."""
    reader_rank = await _classification_rank(db, reader)
    source_rank = await _classification_rank(db, source)
    if reader_rank is None or source_rank is None:
        return SKIP_CLASSIFICATION_UNRESOLVED
    if reader != source and knowledge_sharing_off(level_registry().at_rank(source_rank).key):
        return SKIP_CLASSIFICATION_SHARING_OFF
    return SKIP_CLASSIFICATION_ABOVE_READER if source_rank > reader_rank else None


async def _names(db: AsyncSession, project_ids: list[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    rows = await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
    return {row[0]: row[1] for row in rows.all()}


async def active_bindings(db: AsyncSession, reader_project_id: str) -> list[KnowledgeWorkspaceBinding]:
    statement = (
        select(KnowledgeWorkspaceBinding)
        .where(
            KnowledgeWorkspaceBinding.reader_project_id == reader_project_id,
            KnowledgeWorkspaceBinding.state == BINDING_STATE_ACTIVE,
        )
        .order_by(KnowledgeWorkspaceBinding.created_at, KnowledgeWorkspaceBinding.id)
    )
    return list((await db.execute(statement)).scalars().all())[:MAX_BINDINGS]


async def resolve_scope(db: AsyncSession, primary: AuthorizedWorkspace) -> KnowledgeScope:
    """The reader's own Workspace plus the sources its active bindings admit right now."""
    if primary.on_behalf_of is not None:
        # A bound read never widens further: bindings are not transitive.
        return KnowledgeScope(primary, "")
    bindings = await active_bindings(db, primary.project_id)
    names = await _names(db, [primary.project_id, *(binding.source_project_id for binding in bindings)])
    sources: list[BoundSource] = []
    skipped: dict[str, str] = {}
    for binding in bindings:
        if binding.source_project_id not in names:
            continue
        reason = await _compatibility(db, reader=primary.project_id, source=binding.source_project_id)
        if reason is not None:
            skipped[binding.source_project_id] = reason
            continue
        authorized = AuthorizedWorkspace(
            workspace=parse_workspace_id(binding.source_project_id),
            project_id=binding.source_project_id,
            role=BOUND_READER_ROLE,
            on_behalf_of=primary.project_id,
            # The source's ACL facets apply to the calling user in the bound Workspace too.
            principal_keys=primary.principal_keys,
        )
        sources.append(BoundSource(authorized, names[binding.source_project_id], tuple(binding.products or ())))
    return KnowledgeScope(primary, names.get(primary.project_id, ""), tuple(sources), skipped)


async def create_binding(
    db: AsyncSession,
    *,
    reader: AuthorizedWorkspace,
    source_workspace_id: object,
    products: object,
    reason: object,
    user: User,
) -> KnowledgeWorkspaceBinding:
    """Bind ``reader`` to read the source Workspace; the caller must author in both."""
    if not reader.may_author:
        raise BindingRefusedError("reader_author_required")
    # Authoring the source is the source side's consent; refusal there is indistinguishable from absence.
    source = await authorize_workspace(db, current_user=user, workspace_id=source_workspace_id, require_author=True)
    if source.project_id == reader.project_id:
        raise BindingRefusedError("self_binding")
    try:
        product_keys = list(normalize_products(products)) if products else []
    except InvalidEvidenceRequestError:
        raise BindingRefusedError("invalid_products") from None
    incompatible = await _compatibility(db, reader=reader.project_id, source=source.project_id)
    if incompatible is not None:
        raise BindingRefusedError(incompatible)
    existing = (
        await db.execute(
            select(KnowledgeWorkspaceBinding).where(
                KnowledgeWorkspaceBinding.reader_project_id == reader.project_id,
                KnowledgeWorkspaceBinding.source_project_id == source.project_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None or existing.state != BINDING_STATE_ACTIVE:
        if len(await active_bindings(db, reader.project_id)) >= MAX_BINDINGS:
            raise BindingRefusedError("too_many_bindings")
    binding = existing or KnowledgeWorkspaceBinding(
        reader_project_id=reader.project_id, source_project_id=source.project_id
    )
    binding.products = product_keys
    binding.state = BINDING_STATE_ACTIVE
    binding.reason = " ".join(str(reason or "").split())[:MAX_REASON_CHARS]
    binding.created_by = user.id
    binding.created_at = utc_now()
    binding.revoked_by = binding.revoked_at = None
    if existing is None:
        db.add(binding)
    await db.flush()
    return binding


async def revoke_binding(
    db: AsyncSession, *, workspace: AuthorizedWorkspace, binding_id: str, user: User
) -> KnowledgeWorkspaceBinding | None:
    """Either side revokes: an author of the reader or of the source Workspace."""
    binding = await db.get(KnowledgeWorkspaceBinding, binding_id)
    if binding is None or workspace.project_id not in (binding.reader_project_id, binding.source_project_id):
        return None
    if not workspace.may_author:
        raise BindingRefusedError("author_required")
    binding.state = BINDING_STATE_REVOKED
    binding.revoked_by, binding.revoked_at = user.id, utc_now()
    await db.flush()
    return binding


async def bindings_of(db: AsyncSession, project_id: str) -> tuple[list, list, dict[str, str]]:
    """``(reads_from, read_by, names)``: the Workspace's bindings in both directions, for the admin view."""
    rows = (
        (
            await db.execute(
                select(KnowledgeWorkspaceBinding)
                .where(
                    (KnowledgeWorkspaceBinding.reader_project_id == project_id)
                    | (KnowledgeWorkspaceBinding.source_project_id == project_id)
                )
                .order_by(KnowledgeWorkspaceBinding.created_at)
            )
        )
        .scalars()
        .all()
    )
    names = await _names(db, sorted({r.reader_project_id for r in rows} | {r.source_project_id for r in rows}))
    reads_from = [row for row in rows if row.reader_project_id == project_id]
    read_by = [row for row in rows if row.source_project_id == project_id]
    return reads_from, read_by, names


__all__ = [
    "BindingRefusedError",
    "BoundSource",
    "KnowledgeScope",
    "MAX_BINDINGS",
    "SKIP_CLASSIFICATION_ABOVE_READER",
    "SKIP_CLASSIFICATION_UNRESOLVED",
    "active_bindings",
    "bindings_of",
    "create_binding",
    "resolve_scope",
    "revoke_binding",
]
