"""Auto-extracted router module: panel_office."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.workspace_artifacts import _office_template_import_root, _office_template_upload_root

from ...http_multipart_route import BoundedFormRoute
from .panel_corp_identities import router as panel_corp_identities_router
from .panel_office_fallback import router as fallback_router

router = APIRouter(route_class=BoundedFormRoute)
router.include_router(fallback_router)


@router.post("/chat/api/panel/office-templates/upload")
async def panel_upload_office_template(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.disk_hygiene import run_backend_disk_hygiene
    from ...services.office.storage import (
        OfficeTemplateUploadTooLargeError,
        persist_uploaded_office_template,
    )

    try:
        entry = await persist_uploaded_office_template(
            file_name=file.filename or "template.bin",
            read_chunk=file.read,
            close_file=file.close,
            upload_root=_office_template_upload_root(),
            import_root=_office_template_import_root(),
        )
        # Upload should remain available even if stale package cleanup is skipped.
        try:
            await run_backend_disk_hygiene(
                db,
                dry_run=False,
                include_corp_identity_candidates=False,
                include_office_import_candidates=True,
            )
        except OSError:
            pass
    except OfficeTemplateUploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"template": entry})


@router.get("/chat/api/panel/office-templates/disk-hygiene")
async def panel_preview_office_disk_hygiene(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.disk_hygiene import collect_backend_disk_hygiene_plan

    return JSONResponse(
        await collect_backend_disk_hygiene_plan(
            db,
            include_corp_identity_candidates=True,
            include_office_import_candidates=True,
        )
    )


@router.post("/chat/api/panel/office-templates/disk-hygiene/run")
async def panel_run_office_disk_hygiene(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.disk_hygiene import run_backend_disk_hygiene

    return JSONResponse(
        await run_backend_disk_hygiene(
            db,
            dry_run=False,
            include_corp_identity_candidates=True,
            include_office_import_candidates=True,
        )
    )


router.include_router(panel_corp_identities_router)
