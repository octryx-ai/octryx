"""Admin Engineering Knowledge Pack API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_engineering_knowledge_panel import EngineeringKnowledgeBuildRunCreateRequest
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_build_runs import (
    create_engineering_knowledge_build_run,
    get_engineering_knowledge_build_run,
    list_engineering_knowledge_build_runs,
)
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_graph import (
    list_engineering_knowledge_graph_nodes,
)
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_packs import (
    delete_engineering_knowledge_pack,
    get_engineering_knowledge_pack,
    list_engineering_knowledge_packs,
)
from app.web._context import WORKSPACE_ROOT
from app.web._helpers.api_guards import _require_admin_api

from .panel_engineering_knowledge_federation import router as panel_engineering_knowledge_federation_router

router = APIRouter()


@router.get("/chat/api/panel/engineering-knowledge/packs")
async def panel_list_engineering_knowledge_packs(
    request: Request,
    stack_key: str = "",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_engineering_knowledge_packs(db, stack_key=stack_key, limit=limit, offset=offset)
    )


@router.get("/chat/api/panel/engineering-knowledge/stale-packs")
async def panel_list_stale_engineering_knowledge_packs(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Published packs older than their freshness policy — the re-research
    worklist for keeping post-cutoff knowledge current."""
    await _require_admin_api(request, db)
    from app.services.engineering_knowledge.pack_seed import list_stale_engineering_knowledge_packs

    return JSONResponse({"stale_packs": await list_stale_engineering_knowledge_packs(db)})


@router.get("/chat/api/panel/engineering-knowledge/packs/{pack_id}")
async def panel_get_engineering_knowledge_pack(
    pack_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_engineering_knowledge_pack(db, pack_id=pack_id))


@router.delete("/chat/api/panel/engineering-knowledge/packs/{pack_id}")
async def panel_delete_engineering_knowledge_pack(
    pack_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await delete_engineering_knowledge_pack(db, pack_id=pack_id, admin_id=admin.id))


@router.get("/chat/api/panel/engineering-knowledge/build-runs")
async def panel_list_engineering_knowledge_build_runs(
    request: Request,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_engineering_knowledge_build_runs(db, status=status, limit=limit, offset=offset)
    )


@router.post("/chat/api/panel/engineering-knowledge/build-runs")
async def panel_create_engineering_knowledge_build_run(
    payload: EngineeringKnowledgeBuildRunCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await create_engineering_knowledge_build_run(
            db,
            admin_id=admin.id,
            payload=payload.model_dump(),
            archive_base_path=WORKSPACE_ROOT,
        )
    )


@router.get("/chat/api/panel/engineering-knowledge/build-runs/{build_run_id}")
async def panel_get_engineering_knowledge_build_run(
    build_run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_engineering_knowledge_build_run(db, build_run_id=build_run_id))


@router.get("/chat/api/panel/engineering-knowledge/graph/nodes")
async def panel_list_engineering_knowledge_graph_nodes(
    request: Request,
    query: str = "",
    node_type: str = "",
    status: str = "",
    trust_level: str = "",
    classification: str = "",
    scope_type: str = "",
    scope_id: str = "",
    repository_id: str = "",
    source: str = "",
    reviewer: str = "",
    validity: str = "",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await list_engineering_knowledge_graph_nodes(
            db,
            viewer_id=admin.id,
            query=query,
            node_type=node_type,
            status=status,
            trust_level=trust_level,
            classification=classification,
            scope_type=scope_type,
            scope_id=scope_id,
            repository_id=repository_id,
            source=source,
            reviewer=reviewer,
            validity=validity,
            limit=limit,
            offset=offset,
        )
    )


router.include_router(panel_engineering_knowledge_federation_router)
