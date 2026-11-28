"""Admin › Models: the bundled LiteLLM's model routes (``services/model_gateway/bundled_routes``)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.admin.governance.admin_config_audit_service import record_admin_config_audit
from app.services.model_gateway import bundled_routes
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


def _audit(db: AsyncSession, user, action: str, alias: str, after: dict | None) -> None:
    # The route without its credential: the audit row never holds a key.
    record_admin_config_audit(db, actor_user_id=user.id, action=action, resource_type="model_route",
                              resource_id=alias, project_id=None, before=None, after=after,
                              details={"operation": action.rsplit(".", 1)[-1]})


@router.get("/chat/api/panel/model-routes")
async def panel_list_model_routes(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await bundled_routes.list_routes(db))


@router.post("/chat/api/panel/model-routes")
async def panel_create_model_route(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    route = await bundled_routes.save_route(db, dict(await request.json()))
    _audit(db, user, "admin.model_route.created", route["alias"], route)
    await db.commit()
    return JSONResponse(route)


@router.put("/chat/api/panel/model-routes/{alias}")
async def panel_update_model_route(alias: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    route = await bundled_routes.save_route(db, dict(await request.json()), alias=alias)
    _audit(db, user, "admin.model_route.updated", alias, route)
    await db.commit()
    return JSONResponse(route)


@router.delete("/chat/api/panel/model-routes/{alias}")
async def panel_delete_model_route(alias: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    await bundled_routes.delete_route(db, alias)
    _audit(db, user, "admin.model_route.deleted", alias, None)
    await db.commit()
    return JSONResponse({"deleted": alias})


@router.post("/chat/api/panel/model-routes/{alias}/test")
async def panel_test_model_route(alias: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await bundled_routes.test_route(db, alias))
