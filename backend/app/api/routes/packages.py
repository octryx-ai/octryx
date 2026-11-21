from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.comms.export_package import ExportPackageCreateRequest, ImportPackageRequest
from ...services.access_control import require_existing_workspace
from ...services.auth import get_current_user
from ...services.auth.admin_principal import get_current_admin_user
from ...services.export_package import (
    create_export_package,
    get_export_package,
    import_package,
    list_export_packages,
    list_import_logs,
)

router = APIRouter(prefix="/api/v1/packages", tags=["packages"])


@router.get("/exports")
async def api_list_export_packages(
    package_type: str | None = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_export_packages(db, package_type=package_type, limit=limit)


@router.post("/export")
async def api_create_export_package(
    body: ExportPackageCreateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_export_package(
        db,
        current_user=current_user,
        package_type=body.package_type,
        entity_id=body.entity_id,
    )


@router.get("/exports/{package_id}")
async def api_get_export_package(
    package_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_export_package(db, package_id=package_id)


@router.get("/imports")
async def api_list_import_logs(
    package_type: str | None = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_import_logs(db, package_type=package_type, limit=limit)


@router.post("/import")
async def api_import_package(
    body: ImportPackageRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, body.target_project_id)
    return await import_package(
        db,
        current_user=current_user,
        package_id=body.package_id,
        package_json=body.package_json,
        overwrite_existing=body.overwrite_existing,
        target_project_id=body.target_project_id,
        name_override=body.name_override,
    )
