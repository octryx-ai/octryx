"""Admin panel routes for reviewing the Engineering Knowledge graph and pack versions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_engineering_knowledge_panel import (
    EngineeringKnowledgeGraphEdgeUpsertRequest,
    EngineeringKnowledgeGraphNodeReviewRequest,
    EngineeringKnowledgeGraphNodeUpsertRequest,
    EngineeringKnowledgePackAssignmentRequest,
    EngineeringKnowledgePackRejectRequest,
)
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_graph import (
    get_engineering_knowledge_graph_entity,
    review_engineering_knowledge_graph_node,
    upsert_engineering_knowledge_graph_edge,
    upsert_engineering_knowledge_graph_node,
)
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_versions import (
    assign_engineering_knowledge_pack_version,
    publish_engineering_knowledge_pack_version,
    reject_engineering_knowledge_pack_version,
    search_engineering_knowledge_pack_version_retrieval,
)
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace

router = APIRouter()


@router.post("/chat/api/panel/engineering-knowledge/graph/nodes")
async def panel_upsert_engineering_knowledge_graph_node(
    payload: EngineeringKnowledgeGraphNodeUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.workspace_id)
    return JSONResponse(
        await upsert_engineering_knowledge_graph_node(
            db,
            admin_id=admin.id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.post("/chat/api/panel/engineering-knowledge/graph/edges")
async def panel_upsert_engineering_knowledge_graph_edge(
    payload: EngineeringKnowledgeGraphEdgeUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await upsert_engineering_knowledge_graph_edge(
            db,
            admin_id=admin.id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.get("/chat/api/panel/engineering-knowledge/graph/entities/{entity_ref}")
async def panel_get_engineering_knowledge_graph_entity(
    entity_ref: str,
    request: Request,
    scope_type: str = "global",
    scope_id: str = "",
    include_related: bool = True,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await get_engineering_knowledge_graph_entity(
            db,
            entity_ref=entity_ref,
            scope_type=scope_type,
            scope_id=scope_id or None,
            include_related=include_related,
        )
    )


@router.post("/chat/api/panel/engineering-knowledge/graph/nodes/{node_id}/review")
async def panel_review_engineering_knowledge_graph_node(
    node_id: str,
    payload: EngineeringKnowledgeGraphNodeReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await review_engineering_knowledge_graph_node(
            db,
            node_id=node_id,
            admin_id=admin.id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.post("/chat/api/panel/engineering-knowledge/versions/{version_id}/publish")
async def panel_publish_engineering_knowledge_pack_version(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await publish_engineering_knowledge_pack_version(db, version_id=version_id, admin_id=admin.id)
    )


@router.post("/chat/api/panel/engineering-knowledge/versions/{version_id}/reject")
async def panel_reject_engineering_knowledge_pack_version(
    version_id: str,
    payload: EngineeringKnowledgePackRejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await reject_engineering_knowledge_pack_version(
            db,
            version_id=version_id,
            admin_id=admin.id,
            reason=payload.reason,
        )
    )


@router.get("/chat/api/panel/engineering-knowledge/versions/{version_id}/retrieval-index")
async def panel_search_engineering_knowledge_pack_version_retrieval(
    version_id: str,
    request: Request,
    query: str = "",
    record_kind: str = "",
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await search_engineering_knowledge_pack_version_retrieval(
            db,
            version_id=version_id,
            query=query,
            record_kind=record_kind,
            limit=limit,
        )
    )


@router.post("/chat/api/panel/engineering-knowledge/versions/{version_id}/assignments")
async def panel_assign_engineering_knowledge_pack_version(
    version_id: str,
    payload: EngineeringKnowledgePackAssignmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.workspace_id)
    return JSONResponse(
        await assign_engineering_knowledge_pack_version(
            db,
            version_id=version_id,
            admin_id=admin.id,
            payload=payload.model_dump(exclude_none=True),
        )
    )
