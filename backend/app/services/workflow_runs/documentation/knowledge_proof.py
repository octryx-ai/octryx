"""Knowledge proves the **same** Confluence page the run published, not just the same id and version."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import DocumentationWriteIntent, WorkflowRun
from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_source_sync import (
    ITEM_STATE_INGESTED,
    ITEM_STATE_WITHHELD,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
)
from ....models.runtime.documentation_publication import DOCUMENTATION_SLOT, INTENT_SENT_CONFIRMED
from ....tools._confluence_instance import confluence_instance

REASON_SOURCE_INSTANCE = "source_instance_mismatch"
REASON_SOURCE_CONNECTION = "source_connection_mismatch"

# Publish & prove failure classes (``failure_routes.py`` routes them; the global
# ``CLASS_SAFETY`` is unchanged and still used for binding/instance/connection refusals).
CLASS_PARSE_FAILED = "parse_failed"
CLASS_INDEX_TIMEOUT = "index_timeout"
CLASS_NEEDS_CONFIGURATION = "needs_configuration"
CLASS_AUDIENCE_UNPROVEN = "audience_unproven"
S1_FAILURE_CLASSES = (CLASS_PARSE_FAILED, CLASS_INDEX_TIMEOUT, CLASS_NEEDS_CONFIGURATION, CLASS_AUDIENCE_UNPROVEN)

BINDING_ITEM_MISSING = "item_missing"
BINDING_WITHHELD = "item_withheld"
BINDING_NOT_INGESTED = "item_not_ingested"
BINDING_VERSION = "ledger_version_mismatch"
BINDING_INSTANCE = "ledger_instance_mismatch"
BINDING_HEAD = "head_not_projected"
BINDING_DIGEST = "revision_digest_mismatch"
BINDING_REVISION = "revision_changed"


def sha256_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def as_digest(content_sha256: object) -> str:
    text = str(content_sha256 or "")
    return text if text.startswith("sha256:") else f"sha256:{text}" if text else ""


async def published_intent(db: AsyncSession, run: WorkflowRun) -> DocumentationWriteIntent | None:
    return (await db.execute(
        select(DocumentationWriteIntent).where(
            DocumentationWriteIntent.run_id == run.id,
            DocumentationWriteIntent.slot == DOCUMENTATION_SLOT,
            DocumentationWriteIntent.state == INTENT_SENT_CONFIRMED,
        ).order_by(DocumentationWriteIntent.sent_confirmed_at.desc(), DocumentationWriteIntent.created_at.desc())
        .limit(1))).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class LedgerBinding:
    item_id: str
    source_id: str
    source_key: str
    page_version: int
    instance: str
    revision_id: str
    revision_digest: str
    span_keys: tuple[str, ...]

    @property
    def index_refs(self) -> dict[str, Any]:
        return {"revision_id": self.revision_id, "span_keys": list(self.span_keys)}

    @property
    def index_refs_digest(self) -> str:
        return sha256_json(self.index_refs)


class BindingRefusedError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def binding_class(reason: str) -> str:
    if reason in (BINDING_INSTANCE, BINDING_REVISION):
        return "safety"
    if reason == BINDING_WITHHELD:
        return "permission"
    if reason == BINDING_DIGEST:
        return CLASS_PARSE_FAILED
    return CLASS_INDEX_TIMEOUT


async def ledger_binding(db: AsyncSession, *, connector_id: str, project_id: str, page_id: str, page_version: int,
                         instance: str, revision_id: str | None = None, revision_digest: str | None = None
                         ) -> LedgerBinding:
    item = (await db.execute(select(KnowledgeSourceSyncItem).where(
        KnowledgeSourceSyncItem.connector_id == connector_id, KnowledgeSourceSyncItem.project_id == project_id,
        KnowledgeSourceSyncItem.external_id == str(page_id))
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if item is None:
        raise BindingRefusedError(BINDING_ITEM_MISSING, f"Knowledge holds no item for page {page_id}")
    if item.state == ITEM_STATE_WITHHELD:
        raise BindingRefusedError(BINDING_WITHHELD, "the page is restricted: Knowledge withholds it")
    if item.state != ITEM_STATE_INGESTED or not item.source_id:
        raise BindingRefusedError(BINDING_NOT_INGESTED, f"the page is not ingested (item {item.state})")
    if str(item.version_marker or "") != str(page_version):
        raise BindingRefusedError(BINDING_VERSION, f"Knowledge holds page version {item.version_marker}, not the "
                                                   f"published {page_version}")
    if not instance or str(item.source_instance or "") != instance:
        read_from = item.source_instance or "no recorded instance"
        raise BindingRefusedError(BINDING_INSTANCE, f"Knowledge read the page from {read_from}, not {instance}")
    head = await db.get(KnowledgeSourceHead, item.source_id, populate_existing=True)
    current = head.current_revision_id if head is not None else None
    wanted = head.wanted_revision_id if head is not None else None
    if current is None or (wanted is not None and wanted != current):
        raise BindingRefusedError(BINDING_HEAD, "the index has not projected the ingested revision yet")
    revision = await db.get(KnowledgeSourceRevision, current, populate_existing=True)
    if revision is None or revision.state != REVISION_STATE_PROJECTED or revision.project_id != project_id:
        raise BindingRefusedError(BINDING_HEAD, "the source's current revision is not projected")
    digest = as_digest(revision.content_sha256)
    if digest != as_digest(item.content_sha256):
        raise BindingRefusedError(BINDING_DIGEST, "the projected revision is not the bytes the sync ingested")
    if revision_id is not None and revision.id != revision_id:
        raise BindingRefusedError(BINDING_REVISION, "the source moved to another revision since the binding")
    if revision_digest is not None and digest != revision_digest:
        raise BindingRefusedError(BINDING_DIGEST, "the revision digest is not the recorded one")
    spans = (await db.execute(select(KnowledgeEvidenceSpan.evidence_key).where(
        KnowledgeEvidenceSpan.revision_id == revision.id, KnowledgeEvidenceSpan.project_id == project_id)
        .order_by(KnowledgeEvidenceSpan.span_ordinal))).scalars().all()
    if not spans:
        raise BindingRefusedError(BINDING_HEAD, "the projected revision has no spans")
    return LedgerBinding(item_id=item.id, source_id=str(item.source_id), source_key=item.source_key,
                         page_version=int(page_version), instance=instance, revision_id=revision.id,
                         revision_digest=digest, span_keys=tuple(spans))


def serving_connection_ref(scoped: Any, space_key: str) -> str:
    wanted = str(space_key or "").upper()
    ref = next((ref for key, ref in scoped.by_key.items() if str(key).upper() == wanted), None)
    refs = set(scoped.by_key.values()) or set(scoped.connections)
    return str(ref or (next(iter(refs)) if len(refs) == 1 else ""))


def publication_pin(page: dict[str, Any]) -> Callable[[Any], str]:
    # Same serving connection and instance, never endpoint equality alone.
    from ...knowledge.sources.sync.provenance import scope_connection

    instance, space = str(page.get("instance") or ""), str(page.get("space_key") or "")
    expected = str(page.get("connection_id") or "")

    def pin(scoped: Any) -> str:
        connection = scope_connection(scoped, space)
        serving = confluence_instance(getattr(connection, "base_url", "")) if connection is not None else ""
        if not instance or serving != instance:
            return REASON_SOURCE_INSTANCE
        actual = serving_connection_ref(scoped, space)
        return "" if expected and actual == expected else REASON_SOURCE_CONNECTION

    return pin


async def publication_source_refusal(db: AsyncSession, page: dict[str, Any], row: KnowledgeSourceConnector) -> str:
    from ...knowledge.sources.sync.contract import ConnectorError
    from ...knowledge.sources.sync.scope_connections import resolve_scope_connections

    scope, space = dict(row.scope or {}), str(page.get("space_key") or "").upper()
    covers = space in {str(key).upper() for key in scope.get("spaces") or []}
    trees = scope.get("page_trees") or []
    covers = covers or any(isinstance(tree, dict) and str(tree.get("space_key") or "").upper() == space
                           and str(tree.get("root_page_id") or "") == str(page.get("parent_id") or "")
                           for tree in trees)
    if not covers:
        return "the Knowledge source no longer covers the publication target"
    try:
        scoped = await resolve_scope_connections(db, kind=row.kind, project_id=row.project_id, scope=scope,
                                                 connection_id=row.connection_id)
    except ConnectorError:
        return "the publication's Knowledge connection is not usable"
    return publication_pin(page)(scoped)


__all__ = [
    "CLASS_AUDIENCE_UNPROVEN",
    "CLASS_INDEX_TIMEOUT",
    "CLASS_NEEDS_CONFIGURATION",
    "CLASS_PARSE_FAILED",
    "REASON_SOURCE_INSTANCE",
    "S1_FAILURE_CLASSES",
    "BindingRefusedError",
    "LedgerBinding",
    "as_digest",
    "binding_class",
    "ledger_binding",
    "published_intent",
    "publication_pin",
    "publication_source_refusal",
    "serving_connection_ref",
    "sha256_json",
]
