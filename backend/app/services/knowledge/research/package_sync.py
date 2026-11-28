"""Take an approved knowledge package into the Workspace. Only accepted documents of trusted sources are fetched,
checked again after a redirect."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_packages import (
    DOCUMENT_STATE_ACCEPTED,
    DOCUMENT_STATE_FAILED,
    DOCUMENT_STATE_INGESTED,
    PACKAGE_STATE_FAILED,
    PACKAGE_STATE_READY,
    KnowledgePackage,
    KnowledgePackageDocument,
)
from ...web_search.registry import URL_TRUSTED, load_policy
from ..access.authorization import AuthorizedWorkspace
from ..ingestion.media_types import is_sandboxed_media_type
from ..ingestion.sandboxed_ingest import ingest_sandboxed_source
from ..ingestion.text_ingest import ingest_text_source
from ..ledger.errors import EvidenceLedgerError
from ..runtime import EvidenceRuntime
from ..sources.web_fetch import FetchRefusedError, fetch_public_document

logger = logging.getLogger(__name__)


def source_key_for(product: str, title: str, version: str | None, ordinal: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{product} {version or ''} {title}".lower()).strip("-")
    return (slug[:180] or f"{product}-document") + f"-{ordinal}"


async def _accepted_documents(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, package: KnowledgePackage
) -> list[KnowledgePackageDocument]:
    return (
        (
            await db.execute(
                select(KnowledgePackageDocument)
                .where(
                    KnowledgePackageDocument.package_id == package.id,
                    KnowledgePackageDocument.project_id == authorized.project_id,
                    KnowledgePackageDocument.state == DOCUMENT_STATE_ACCEPTED,
                )
                .order_by(KnowledgePackageDocument.ordinal)
            )
        )
        .scalars()
        .all()
    )


async def _sync_document(
    db: AsyncSession,
    document: KnowledgePackageDocument,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    package: KnowledgePackage,
    policy,
    created_by: str | None,
) -> str:
    outcome = "ingested"
    try:
        fetched = await fetch_public_document(document.url)
        if policy.state_of(fetched.url, package.product) != URL_TRUSTED:
            raise FetchRefusedError("redirect_untrusted")
        ingest = ingest_sandboxed_source if is_sandboxed_media_type(fetched.media_type) else ingest_text_source
        ingested = await ingest(
            db,
            runtime=runtime,
            authorized=authorized,
            source_key=source_key_for(package.product, document.title, document.version, document.ordinal),
            display_title=document.title,
            declared_media_type=fetched.media_type,
            data=fetched.data,
            created_by=created_by,
            source_url=document.url,
            products=package.product,
            version=document.version,
        )
        document.source_id = ingested.source_id
        document.state = DOCUMENT_STATE_INGESTED
    except FetchRefusedError as error:
        outcome = f"fetch_{error.reason}"
    except EvidenceLedgerError as error:
        await db.rollback()
        outcome = error.state.value
    if outcome != "ingested":
        document = await db.get(KnowledgePackageDocument, document.id)
        document.state = DOCUMENT_STATE_FAILED
    document.outcome = outcome[:40]
    return outcome


async def sync_package(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    package: KnowledgePackage,
    created_by: str | None,
) -> dict[str, int]:
    documents = await _accepted_documents(db, authorized=authorized, package=package)
    counts = {"ingested": 0, "failed": 0, "held": 0}
    policy = await load_policy(db, project_id=authorized.project_id)
    for document in documents:
        if policy.state_of(document.url, package.product) != URL_TRUSTED:
            document.outcome = "source_not_trusted"
            counts["held"] += 1
            await db.commit()
            continue
        outcome = await _sync_document(
            db,
            document,
            runtime=runtime,
            authorized=authorized,
            package=package,
            policy=policy,
            created_by=created_by,
        )
        counts["ingested" if outcome == "ingested" else "failed"] += 1
        await db.commit()
    package = await db.get(KnowledgePackage, package.id)
    # A catalog grows over several approvals: it is ready as soon as any of its documents is in.
    ingested_any = (
        await db.execute(
            select(KnowledgePackageDocument.id).where(
                KnowledgePackageDocument.package_id == package.id,
                KnowledgePackageDocument.state == DOCUMENT_STATE_INGESTED,
            )
        )
    ).first()
    package.state = PACKAGE_STATE_READY if ingested_any else PACKAGE_STATE_FAILED
    await db.commit()
    logger.info("Knowledge package synced: %s workspace=%s", counts, authorized.project_id)
    return counts


__all__ = ["source_key_for", "sync_package"]
