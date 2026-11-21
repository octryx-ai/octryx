"""Admin panel API for the entity knowledge graph (gold layer).

Serves the REAL knowledge graph (``knowledge_graph_nodes``/``edges``, claims,
communities) — not the medallion provenance view — plus a retrieval preview
that shows exactly the context block an agent would receive for a query.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.knowledge_graph.visualization import build_entity_graph, get_entity_node_detail
from app.services.knowledge_retrieval import build_context_block, retrieve_knowledge
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace

router = APIRouter()


async def _private_ids(db: AsyncSession) -> frozenset[str]:
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import Project  # noqa: PLC0415

    return frozenset(row[0] for row in (await db.execute(
        select(Project.id).where(Project.access_mode == "private"))).all())


async def _admin_scope(db: AsyncSession, project_id: str) -> tuple[frozenset[str], list[str] | None]:
    """The admin knowledge views never reach a private Workspace. ``(private ids, project ids)``;
    a named private one is 404, an unnamed scope is every other Workspace (plus the instance-global knowledge)."""
    private = await _private_ids(db)
    if project_id:
        if project_id in private:
            raise HTTPException(status_code=404, detail="Project not found")
        return private, [project_id]
    if not private:
        return private, None
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import Project  # noqa: PLC0415

    others = [row[0] for row in (await db.execute(select(Project.id).where(Project.access_mode != "private"))).all()]
    return private, others or ["-"]  # never an empty list: that would mean "every Workspace"


@router.get("/chat/api/panel/knowledge/entity-graph")
async def panel_entity_graph(
    request: Request,
    project_id: str = "",
    query: str = "",
    node_types: str = "",
    focus_node_id: str = "",
    max_nodes: int = 150,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    private, _scope = await _admin_scope(db, project_id)
    types = [part.strip().lower() for part in node_types.split(",") if part.strip()]
    payload = await build_entity_graph(
        db,
        exclude_project_ids=private,
        project_id=project_id,
        query=query,
        node_types=types or None,
        focus_node_id=focus_node_id,
        max_nodes=max_nodes,
    )
    return JSONResponse(payload)


@router.get("/chat/api/panel/knowledge/entity-graph/node/{node_id}")
async def panel_entity_graph_node(
    request: Request,
    node_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from app.models import KnowledgeGraphNode  # noqa: PLC0415

    node = await db.get(KnowledgeGraphNode, node_id)
    if node is not None and node.project_id and node.project_id in await _private_ids(db):
        raise HTTPException(status_code=404, detail="Knowledge graph node not found")
    detail = await get_entity_node_detail(db, node_id=node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Knowledge graph node not found")
    return JSONResponse(detail)


def _federation_signing_key() -> str:
    from app.config import get_settings

    key = str(getattr(get_settings(), "knowledge_federation_signing_key", None) or "").strip()
    if len(key) < 16:
        raise HTTPException(
            status_code=409,
            detail=(
                "needs_configuration: set OCTRYX_KNOWLEDGE_FEDERATION_SIGNING_KEY "
                "(min 16 chars) to use entity-graph federation"
            ),
        )
    return key


class FederationExportRequest(BaseModel):
    project_id: str = ""
    node_types: list[str] = Field(default_factory=list)
    max_nodes: int = Field(default=5000, ge=1, le=5000)


@router.post("/chat/api/panel/knowledge/entity-graph/federation/export")
async def panel_entity_graph_federation_export(
    request: Request,
    body: FederationExportRequest,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, body.project_id)
    from app.services.knowledge_graph.federation import (
        export_entity_graph_package,
        sign_entity_graph_package,
    )

    await _admin_scope(db, body.project_id)
    signing_key = _federation_signing_key()
    package = await export_entity_graph_package(
        db,
        source_instance=request.url.hostname or "local",
        project_id=body.project_id or None,
        node_types=body.node_types or None,
        max_nodes=body.max_nodes,
    )
    return JSONResponse(sign_entity_graph_package(package, signing_key=signing_key))


class FederationImportRequest(BaseModel):
    package: dict


@router.post("/chat/api/panel/knowledge/entity-graph/federation/import")
async def panel_entity_graph_federation_import(
    request: Request,
    body: FederationImportRequest,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from app.services.knowledge_graph.federation import (
        EntityGraphPackageError,
        import_entity_graph_package,
    )

    signing_key = _federation_signing_key()
    try:
        result = await import_entity_graph_package(db, body.package, signing_key=signing_key)
    except EntityGraphPackageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return JSONResponse(result)


class RetrievalPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: str = Field(default="mix")
    project_id: str = ""
    node_limit: int = Field(default=8, ge=1, le=25)
    chunk_limit: int = Field(default=6, ge=1, le=25)


@router.post("/chat/api/panel/knowledge/retrieval-preview")
async def panel_retrieval_preview(
    request: Request,
    body: RetrievalPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, body.project_id)
    _private, scope = await _admin_scope(db, body.project_id)
    result = await retrieve_knowledge(
        db,
        query=body.query,
        project_ids=scope,
        mode=body.mode,
        node_limit=body.node_limit,
        chunk_limit=body.chunk_limit,
    )
    result["context_block"] = build_context_block(result)
    return JSONResponse(result)


__all__ = ["router"]
