"""Admin panel routes for Corporate Identity profiles and their Office templates."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.web._helpers.api_guards import _require_admin_api

from ...http_multipart_route import BoundedFormRoute
from .panel_runtimes import router as panel_runtimes_router

router = APIRouter(route_class=BoundedFormRoute)


@router.get("/chat/api/panel/corp-identities")
async def panel_list_corp_identities(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import list_corp_identity_profiles

    return JSONResponse(await list_corp_identity_profiles(db))


@router.post("/chat/api/panel/corp-identities/upload")
async def panel_upload_corp_identity(
    request: Request,
    file: UploadFile = File(...),
    merge: bool = False,
    profile_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity.uploads import (
        CorpIdentityUploadTooLargeError,
        save_uploaded_corp_identity_profile_from_stream,
    )

    try:
        profile = await save_uploaded_corp_identity_profile_from_stream(
            db,
            file_name=file.filename or "identity-template.potx",
            read_chunk=file.read,
            close_file=file.close,
            merge_into_profile_id=profile_id if merge else None,
        )
    except CorpIdentityUploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"profile": profile})


@router.get("/chat/api/panel/corp-identities/{profile_id}")
async def panel_get_corp_identity(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import get_corp_identity_profile_detail

    try:
        return JSONResponse(await get_corp_identity_profile_detail(db, profile_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.post("/chat/api/panel/corp-identities/{profile_id}/default")
async def panel_set_default_corp_identity(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import set_default_corp_identity_profile

    try:
        return JSONResponse(await set_default_corp_identity_profile(db, profile_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.get("/chat/api/panel/corp-identities/{profile_id}/corporate-identity")
async def panel_corp_identity_brief(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from app.services.corp_identity.profile_edits import get_corp_identity_brief

    try:
        return JSONResponse(await get_corp_identity_brief(db, profile_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.get("/chat/api/panel/corp-identities/{profile_id}/asset")
async def panel_corp_identity_asset(
    profile_id: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from pathlib import Path

    from ...services.corp_identity_service import get_corp_identity_profile_detail

    try:
        profile = await get_corp_identity_profile_detail(db, profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc

    profile_root = Path(str(profile.get("profile_root") or "")).expanduser().resolve()
    # Resolve inside the profile root only — a relative asset path from the
    # catalog, never an absolute or traversing path from the caller.
    candidate = (profile_root / str(path or "")).resolve()
    if not str(candidate).startswith(str(profile_root) + "/") or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(str(candidate))


@router.post("/chat/api/panel/corp-identities/{profile_id}/example-deck")
async def panel_attach_corp_identity_example_deck(
    profile_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity.uploads import (
        CorpIdentityUploadTooLargeError,
        attach_example_deck_from_stream,
    )

    try:
        profile = await attach_example_deck_from_stream(
            db,
            profile_id=profile_id,
            file_name=file.filename or "example.pptx",
            read_chunk=file.read,
            close_file=file.close,
        )
    except CorpIdentityUploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"profile": profile})


@router.delete("/chat/api/panel/corp-identities/{profile_id}/example-deck")
async def panel_clear_corp_identity_example_deck(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import clear_example_deck_from_corp_identity_profile

    try:
        return JSONResponse({"profile": await clear_example_deck_from_corp_identity_profile(db, profile_id=profile_id)})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.post("/chat/api/panel/corp-identities/{profile_id}/reextract")
async def panel_reextract_corp_identity(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import reextract_corp_identity_profile

    try:
        return JSONResponse({"profile": await reextract_corp_identity_profile(db, profile_id)})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.delete("/chat/api/panel/corp-identities/{profile_id}")
async def panel_delete_corp_identity(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import delete_corp_identity_profile

    try:
        return JSONResponse(await delete_corp_identity_profile(db, profile_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corporate identity profile not found") from exc


@router.put("/chat/api/panel/corp-identities/{profile_id}/templates/{template_id}")
async def panel_update_template(
    profile_id: str,
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from app.services.corp_identity.profile_edits import update_corp_identity_template

    try:
        return JSONResponse(await update_corp_identity_template(db, profile_id, template_id, await request.json()))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/api/panel/corp-identities/{profile_id}/templates/{template_id}")
async def panel_delete_template(
    profile_id: str,
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.corp_identity_service import delete_corp_identity_template

    try:
        return JSONResponse(await delete_corp_identity_template(db, profile_id, template_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


router.include_router(panel_runtimes_router)
