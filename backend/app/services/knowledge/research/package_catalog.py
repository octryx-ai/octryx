"""An author's own edits to a knowledge package catalog (Knowledge, research packages).

Research proposes; the author owns the catalog. An author can add a source the research missed,
correct a proposed title, version, role or URL, and remove a document. Every value goes through the
same validation as a researched one, so a hand-added source is indistinguishable from a researched
one downstream, except that its rationale says who added it. An ingested document is fixed; to
change it, add a corrected document and remove the old one's source.

A hand-added document is accepted only when its source is trusted; otherwise it waits as a proposal
until an admin trusts the source (``services/web_search/registry.py``).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_packages import (
    DOCUMENT_STATE_ACCEPTED,
    DOCUMENT_STATE_INGESTED,
    DOCUMENT_STATE_PROPOSED,
    KnowledgePackage,
    KnowledgePackageDocument,
)
from ...web_search.registry import URL_TRUSTED, load_policy
from ..ledger.errors import InvalidEvidenceRequestError
from ..sources.scope import normalize_version
from ..sources.source_url import normalize_source_url
from .research_steps import ROLES


def _validated(url: object, title: object, version: object, role: object) -> dict:
    normalized = normalize_source_url(url)
    if not normalized or not normalized.startswith("https://") or role not in ROLES:
        raise InvalidEvidenceRequestError()
    text = " ".join(str(title or "").split())[:300]
    if not text:
        raise InvalidEvidenceRequestError()
    return {"url": normalized, "title": text, "version": normalize_version(version) if version else None, "role": role}


async def add_document(
    db: AsyncSession,
    package: KnowledgePackage,
    *,
    url: object,
    title: object,
    version: object,
    role: object,
    added_by: str,
) -> KnowledgePackageDocument:
    values = _validated(url, title, version, role)
    policy = await load_policy(db, project_id=package.project_id)
    trusted = policy.state_of(values["url"], package.product) == URL_TRUSTED
    highest = (
        await db.execute(
            select(func.max(KnowledgePackageDocument.ordinal)).where(KnowledgePackageDocument.package_id == package.id)
        )
    ).scalar_one_or_none()
    document = KnowledgePackageDocument(
        package_id=package.id,
        project_id=package.project_id,
        ordinal=int(highest or 0) + 1,
        rationale=f"Added by an author ({added_by}).",
        state=DOCUMENT_STATE_ACCEPTED if trusted else DOCUMENT_STATE_PROPOSED,
        **values,
    )
    db.add(document)
    await db.commit()
    return document


async def update_document(
    db: AsyncSession, document: KnowledgePackageDocument, *, url: object, title: object, version: object, role: object
) -> KnowledgePackageDocument:
    if document.state == DOCUMENT_STATE_INGESTED:
        raise InvalidEvidenceRequestError()
    for key, value in _validated(url, title, version, role).items():
        setattr(document, key, value)
    package = await db.get(KnowledgePackage, document.package_id)
    policy = await load_policy(db, project_id=document.project_id)
    if document.state == DOCUMENT_STATE_ACCEPTED and policy.state_of(document.url, package.product) != URL_TRUSTED:
        document.state = DOCUMENT_STATE_PROPOSED
    await db.commit()
    return document


async def remove_document(db: AsyncSession, document: KnowledgePackageDocument) -> None:
    if document.state == DOCUMENT_STATE_INGESTED:
        raise InvalidEvidenceRequestError()
    await db.delete(document)
    await db.commit()


__all__ = ["add_document", "remove_document", "update_document"]
