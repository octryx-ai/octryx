"""Admin panel routes for Engineering Knowledge quality and federation feeds, packages and usage."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.admin.engineering_knowledge._admin_engineering_knowledge_federation import (
    create_engineering_knowledge_federation_panel_feed,
    disable_engineering_knowledge_federation_panel_feed,
    get_engineering_knowledge_federation_panel,
    get_engineering_knowledge_federation_panel_usage,
    get_engineering_knowledge_quality_panel,
    import_engineering_knowledge_federation_panel_package,
    preview_engineering_knowledge_federation_panel_export,
    publish_engineering_knowledge_federation_panel_package,
    record_engineering_knowledge_federation_panel_sync_failure,
    record_engineering_knowledge_federation_panel_usage,
    review_engineering_knowledge_federation_panel_import,
)
from app.web._helpers.api_guards import _require_admin_api

from .panel_engineering_knowledge_review import router as panel_engineering_knowledge_review_router

router = APIRouter()


@router.get("/chat/api/panel/engineering-knowledge/quality")
async def panel_get_engineering_knowledge_quality(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_engineering_knowledge_quality_panel(db, limit=limit))


@router.get("/chat/api/panel/engineering-knowledge/federation")
async def panel_get_engineering_knowledge_federation(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_engineering_knowledge_federation_panel(db, limit=limit))


@router.post("/chat/api/panel/engineering-knowledge/federation/feeds")
async def panel_create_engineering_knowledge_federation_feed(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await create_engineering_knowledge_federation_panel_feed(db, payload=payload, current_user=admin)
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/engineering-knowledge/federation/packages/publish")
async def panel_publish_engineering_knowledge_federation_package(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await publish_engineering_knowledge_federation_panel_package(db, payload=payload, current_user=admin)
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/engineering-knowledge/federation/export-preview")
async def panel_preview_engineering_knowledge_federation_export(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await preview_engineering_knowledge_federation_panel_export(db, payload=payload, current_user=admin)
    )


@router.post("/chat/api/panel/engineering-knowledge/federation/feeds/{feed_id}/import-package")
async def panel_import_engineering_knowledge_federation_package(
    feed_id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await import_engineering_knowledge_federation_panel_package(
        db,
        feed_id=feed_id,
        payload=payload,
        current_user=admin,
    )
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/engineering-knowledge/federation/feeds/{feed_id}/sync-failure")
async def panel_record_engineering_knowledge_federation_sync_failure(
    feed_id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await record_engineering_knowledge_federation_panel_sync_failure(
        db,
        feed_id=feed_id,
        payload=payload,
        current_user=admin,
    )
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/engineering-knowledge/federation/feeds/{feed_id}/disable")
async def panel_disable_engineering_knowledge_federation_feed(
    feed_id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await disable_engineering_knowledge_federation_panel_feed(
        db,
        feed_id=feed_id,
        payload=payload,
        current_user=admin,
    )
    await db.commit()
    return JSONResponse(result)


@router.get("/chat/api/panel/engineering-knowledge/federation/usage")
async def panel_get_engineering_knowledge_federation_usage(
    request: Request,
    package_id: str = "",
    package_record_id: str = "",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await get_engineering_knowledge_federation_panel_usage(
            db,
            package_id=package_id or None,
            package_record_id=package_record_id or None,
            limit=limit,
        )
    )


@router.post("/chat/api/panel/engineering-knowledge/federation/usage")
async def panel_record_engineering_knowledge_federation_usage(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await record_engineering_knowledge_federation_panel_usage(db, payload=payload, current_user=admin)
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/engineering-knowledge/federation/packages/{package_record_id}/review")
async def panel_review_engineering_knowledge_federation_import(
    package_record_id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    result = await review_engineering_knowledge_federation_panel_import(
        db,
        package_record_id=package_record_id,
        payload=payload,
        current_user=admin,
    )
    await db.commit()
    return JSONResponse(result)


router.include_router(panel_engineering_knowledge_review_router)
