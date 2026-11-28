"""Research-built knowledge packages of a Workspace: research, review, approve."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.project.knowledge_packages import (
    DOCUMENT_STATE_ACCEPTED,
    DOCUMENT_STATE_PROPOSED,
    DOCUMENT_STATE_REJECTED,
    PACKAGE_STATE_SYNCING,
    KnowledgePackage,
    KnowledgePackageDocument,
)
from ....services.auth import get_current_user
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.research.model import ResearchModelUnavailableError
from ....services.knowledge.research.package_catalog import add_document, remove_document, update_document
from ....services.knowledge.research.package_research import extend_package, research_package
from ....services.knowledge.research.package_sync import sync_package
from ....services.knowledge.runtime import get_evidence_runtime
from ....services.web_search.registry import URL_TRUSTED, load_policy
from ._knowledge_evidence_http import evidence_http_error
from ._knowledge_package_http import (
    CatalogDocument,
    DocumentDecisions,
    ExtendRequest,
    ResearchRequest,
    _authorized,
    _detail,
    _document,
    _package,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/packages", tags=["workspace-knowledge"])


# Kept in this module: its OpenAPI schema name carries the module path (another ``ApproveRequest`` exists).
class ApproveRequest(BaseModel):
    extract_graph: bool = False


@router.get("")
async def list_packages(
    workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    rows = (
        (
            await db.execute(
                select(KnowledgePackage)
                .where(KnowledgePackage.project_id == authorized.project_id)
                .order_by(KnowledgePackage.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return {"packages": [await _detail(db, row) for row in rows]}


@router.post("")
async def research_new_package(
    workspace_id: str,
    body: ResearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Research a package from the web; the result is a draft to review, nothing is ingested yet."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    try:
        package = await research_package(
            db,
            authorized=authorized,
            topic=body.topic,
            product=body.product,
            versions=body.versions,
            created_by=current_user.id,
        )
    except ResearchModelUnavailableError as error:
        raise HTTPException(
            status_code=503, detail=f"No governed model may research for this workspace ({error.state})."
        ) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await _detail(db, package)


@router.get("/{package_id}")
async def get_package(
    workspace_id: str,
    package_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=False)
    return await _detail(db, await _package(db, authorized, package_id))


@router.patch("/{package_id}/documents")
async def decide_documents(
    workspace_id: str,
    package_id: str,
    body: DocumentDecisions,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    policy = await load_policy(db, project_id=authorized.project_id)
    held: list[str] = []
    for document_id, decision in body.decisions.items():
        document = await db.get(KnowledgePackageDocument, document_id)
        if document is None or document.package_id != package.id:
            continue
        if document.state not in (DOCUMENT_STATE_PROPOSED, DOCUMENT_STATE_ACCEPTED, DOCUMENT_STATE_REJECTED):
            continue
        if decision == "accepted" and policy.state_of(document.url, package.product) != URL_TRUSTED:
            held.append(document.id)
            continue
        document.state = DOCUMENT_STATE_ACCEPTED if decision == "accepted" else DOCUMENT_STATE_REJECTED
    await db.commit()
    return {**await _detail(db, package), "held_untrusted": held}


@router.post("/{package_id}/approve")
async def approve_package(
    workspace_id: str,
    package_id: str,
    body: ApproveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch and ingest the accepted documents; optionally owe their extraction into the graph."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    try:
        runtime = get_evidence_runtime()
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    package.state = PACKAGE_STATE_SYNCING
    package.approved_by = current_user.id
    await db.commit()
    counts = await sync_package(db, runtime=runtime, authorized=authorized, package=package, created_by=current_user.id)
    graph_owed = 0
    if body.extract_graph and counts["ingested"]:
        from ....services.knowledge.temporal.extraction_requests import request_graph_extraction

        try:
            graph_owed = (
                await request_graph_extraction(db, runtime=runtime, authorized=authorized, product=package.product)
            ).revisions_owed
        except EvidenceLedgerError:
            graph_owed = 0
    detail = await _detail(db, await _package(db, authorized, package_id))
    return {**detail, "counts": counts, "graph_revisions_owed": graph_owed}


@router.post("/{package_id}/documents")
async def add_package_document(
    workspace_id: str,
    package_id: str,
    body: CatalogDocument,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """An author adds a source to the catalog by hand; accepted when its source is trusted, else proposed."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    try:
        await add_document(
            db,
            package,
            url=body.url,
            title=body.title,
            version=body.version,
            role=body.role,
            added_by=current_user.username,
        )
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await _detail(db, package)


@router.put("/{package_id}/documents/{document_id}")
async def edit_package_document(
    workspace_id: str,
    package_id: str,
    document_id: str,
    body: CatalogDocument,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    try:
        await update_document(
            db,
            await _document(db, package, document_id),
            url=body.url,
            title=body.title,
            version=body.version,
            role=body.role,
        )
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await _detail(db, package)


@router.delete("/{package_id}/documents/{document_id}")
async def remove_package_document(
    workspace_id: str,
    package_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    try:
        await remove_document(db, await _document(db, package, document_id))
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return await _detail(db, package)


@router.post("/{package_id}/research")
async def research_more(
    workspace_id: str,
    package_id: str,
    body: ExtendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Commission a further research round; new sources are appended as proposals to review."""
    authorized = await _authorized(db, current_user, workspace_id, author=True)
    package = await _package(db, authorized, package_id)
    try:
        added = await extend_package(db, authorized=authorized, package=package, instruction=body.instruction)
    except ResearchModelUnavailableError as error:
        raise HTTPException(
            status_code=503, detail=f"No governed model may research for this workspace ({error.state})."
        ) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    return {**(await _detail(db, package)), "added": added}
