"""Request bodies, lookups and the detail view of the Workspace knowledge package routes."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...models.project.knowledge_packages import KnowledgePackage, KnowledgePackageDocument
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.web_search.patterns import suggested_pattern
from ...services.web_search.registry import load_policy
from ._knowledge_evidence_http import evidence_http_error


class ResearchRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    product: str | None = Field(default=None, max_length=60)
    versions: list[str] | None = Field(default=None, max_length=8)


class DocumentDecisions(BaseModel):
    decisions: dict[str, Literal["accepted", "rejected"]] = Field(max_length=100)


class CatalogDocument(BaseModel):
    url: str = Field(min_length=9, max_length=2048)
    title: str = Field(min_length=1, max_length=300)
    version: str | None = Field(default=None, max_length=40)
    role: str = Field(min_length=3, max_length=40)


class ExtendRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=500)


async def _authorized(db, user, workspace_id: str, *, author: bool) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=author)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _package(db, authorized: AuthorizedWorkspace, package_id: str) -> KnowledgePackage:
    package = await db.get(KnowledgePackage, package_id)
    if package is None or package.project_id != authorized.project_id:
        raise HTTPException(status_code=404, detail="Knowledge package not found.")
    return package


async def _detail(db, package: KnowledgePackage) -> dict:
    documents = (
        (
            await db.execute(
                select(KnowledgePackageDocument)
                .where(KnowledgePackageDocument.package_id == package.id)
                .order_by(KnowledgePackageDocument.ordinal)
            )
        )
        .scalars()
        .all()
    )
    policy = await load_policy(db, project_id=package.project_id)
    return {
        "id": package.id,
        "topic": package.topic,
        "title": package.title,
        "product": package.product,
        "versions": list(package.versions or []),
        "state": package.state,
        "research": dict(package.research or {}),
        "documents": [
            {
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "version": item.version,
                "role": item.role,
                "rationale": item.rationale,
                "state": item.state,
                "outcome": item.outcome,
                # The registry's current word on the document's source, and the pattern an admin
                # would trust for it; only trusted documents can be accepted and ingested.
                "source_state": policy.state_of(item.url, package.product) or "unknown",
                "source_pattern": suggested_pattern(item.url),
            }
            for item in documents
        ],
    }


async def _document(db, package: KnowledgePackage, document_id: str) -> KnowledgePackageDocument:
    document = await db.get(KnowledgePackageDocument, document_id)
    if document is None or document.package_id != package.id:
        raise HTTPException(status_code=404, detail="Package document not found.")
    return document
