"""The Workspace knowledge graph: explicit extraction, status, and version changes.

Thin: authenticate, authorize the Workspace (authoring role to request an extraction), delegate to
``services/knowledge/temporal``, and map the fixed states. Graphiti is imported only when a route
actually needs the graph, because it is part of the optional ``knowledge`` extra.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceGraphNotConfiguredError, EvidenceLedgerError
from ...services.knowledge.retrieval.locator import citation_link
from ...services.knowledge.runtime import get_evidence_runtime
from ...services.knowledge.temporal.change_types import CHANGE_EDGE_TYPES
from ...services.knowledge.temporal.errors import GraphStoreError
from ...services.knowledge.temporal.extraction_requests import GraphStatus, graph_status, request_graph_extraction
from ._knowledge_evidence_http import evidence_http_error

CHANGE_KINDS = frozenset(CHANGE_EDGE_TYPES)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])

_GRAPH_DETAILS = {
    EvidenceGraphNotConfiguredError: (
        "Relationship extraction is not set up on this installation yet."
    )
}


class GraphExtractionRequest(BaseModel):
    product: str = Field(min_length=1, max_length=60)
    # One subject version, or the range (from_version, to_version]; neither means every version.
    version: str | None = Field(default=None, max_length=40)
    from_version: str | None = Field(default=None, max_length=40)
    to_version: str | None = Field(default=None, max_length=40)


class ChangesRequest(BaseModel):
    product: str = Field(min_length=1, max_length=60)
    to_version: str = Field(min_length=1, max_length=40)
    from_version: str | None = Field(default=None, max_length=40)
    query: str | None = Field(default=None, max_length=500)
    limit: int | None = Field(default=None, ge=1, le=200)
    # Only typed change records (REMOVED, RENAMED, …, INTRODUCED); false also lists untyped facts.
    changes_only: bool = True


def _error(error: EvidenceLedgerError) -> HTTPException:
    return evidence_http_error(error, details_by_error_type=_GRAPH_DETAILS)


def _status(status: GraphStatus) -> dict:
    return {
        "episodes": status.episodes,
        "pending_revisions": status.pending_revisions,
        # Episodes per extraction profile; stale ones are purged before their product is extracted again.
        "current_profile": status.current_profile,
        "profiles": status.profiles,
        "stale_episodes": status.stale_episodes,
    }


def _capabilities() -> dict:
    """Whether this installation can read extracted relationships, and extract new ones."""
    try:
        runtime = get_evidence_runtime()
    except EvidenceLedgerError:
        return {"readable": False, "extractable": False}
    with_embedding = runtime.embedding is not None
    return {"readable": with_embedding, "extractable": with_embedding}


@router.post("/graph/extract")
async def request_workspace_graph_extraction(
    workspace_id: str,
    body: GraphExtractionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Owe graph extraction for one product's current revisions; it runs in the background worker.

    Revisions of the product still holding an earlier extraction profile are owed too
    (``stale_revisions_owed``), because the product's graph is purged of that profile first.
    """
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
        owed = await request_graph_extraction(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            product=body.product,
            version=body.version,
            from_version=body.from_version,
            to_version=body.to_version,
        )
        status = await graph_status(db, authorized.project_id)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise _error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "revisions_owed": owed.revisions_owed,
        "stale_revisions_owed": owed.stale_revisions_owed,
        **_status(status),
    }


@router.get("/graph")
async def get_workspace_graph_status(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise _error(error) from None
    status = await graph_status(db, authorized.project_id)
    return {"workspace_id": authorized.project_id, **_status(status), **_capabilities()}


@router.post("/changes")
async def list_knowledge_changes(
    workspace_id: str,
    body: ChangesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cited facts that changed in a product between two versions."""
    from ...services.knowledge.access.bindings import resolve_scope
    from ...services.knowledge.temporal.scoped_changes import scoped_changes

    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        scope = await resolve_scope(db, authorized)
        facts_workspace_id, result = await scoped_changes(
            db,
            runtime=get_evidence_runtime(),
            scope=scope,
            product=body.product,
            to_version=body.to_version,
            from_version=body.from_version,
            query=body.query,
            limit=body.limit,
            kinds=CHANGE_KINDS if body.changes_only else None,
        )
    except EvidenceLedgerError as error:
        raise _error(error) from None
    except GraphStoreError:
        raise HTTPException(status_code=503, detail="The knowledge graph is unavailable.") from None
    return {
        "workspace_id": authorized.project_id,
        # The Workspace whose extracted facts answer: this one, or a bound library.
        "facts_workspace": scope.name_of(facts_workspace_id),
        "state": result.state,
        "product": result.product,
        "from_version": result.from_version,
        "to_version": result.to_version,
        "versions": list(result.versions),
        # Totals per kind across the whole range; the facts below are one page of them.
        "kind_counts": result.kind_counts,
        "episodes": result.episodes,
        "facts": [
            {
                "fact": item.fact,
                "relation": item.relation,
                "subject": item.source_entity,
                "object": item.target_entity,
                "version": item.version,
                "citation": item.citation.citation,
                "cite_as": citation_link(item.citation),
                "source_title": item.citation.source_title,
                "source_url": item.citation.source_url,
                "section": " > ".join(item.citation.section_path) or None,
                "evidence_key": item.citation.evidence_key,
                "supporting_episodes": item.supporting_episodes,
            }
            for item in result.facts
        ],
    }


@router.get("/graph/explorer")
async def get_current_graph_explorer(
    workspace_id: str,
    query: str = Query(default="", max_length=500),
    focus_node_id: str = Query(default="", max_length=100),
    max_nodes: int = Query(default=150, ge=2, le=150),
    layers: str = Query(default="", max_length=100),
    expand_node_id: str = Query(default="", max_length=100),
    # The ids the client already shows (comma-separated); up to 150 ids of 64 characters.
    current_node_ids: str = Query(default="", max_length=12000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from ...services.knowledge.structured.workspace_graph import (
        UnknownLayerError,
        build_workspace_graph,
        parse_layers,
    )

    try:
        selected = parse_layers(layers)
    except UnknownLayerError:
        raise HTTPException(422, "Unknown graph layer") from None
    if expand_node_id and focus_node_id:
        raise HTTPException(422, "Use either focus_node_id (replace the view) or expand_node_id (add to it)")
    current = frozenset(item.strip() for item in current_node_ids.split(",") if item.strip())
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        # Extracted (Graphiti) and deterministic structured layers in one bounded window.
        return await build_workspace_graph(
            db, runtime=get_evidence_runtime(), authorized=authorized,
            query=query, focus_node_id=focus_node_id, max_nodes=max_nodes, layers=selected,
            expand_node_id=expand_node_id, current_node_ids=current,
        )
    except EvidenceLedgerError as error:
        raise _error(error) from None


@router.get("/graph/explorer/nodes/{node_id}")
async def get_current_graph_node(
    workspace_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from ...services.knowledge.structured.explorer import structured_node_detail
    from ...services.knowledge.structured.workspace_graph import is_structured_id
    from ...services.knowledge.temporal.visualization import current_graph_node

    if len(node_id) > 100:
        raise HTTPException(404, "Knowledge graph node not found")
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        if is_structured_id(node_id):
            result = await structured_node_detail(db, authorized=authorized, node_id=node_id)
        else:
            result = await current_graph_node(
                db, runtime=get_evidence_runtime(), authorized=authorized, node_id=node_id
            )
    except EvidenceLedgerError as error:
        raise _error(error) from None
    if result is None:
        raise HTTPException(404, "Knowledge graph node not found")
    return result
