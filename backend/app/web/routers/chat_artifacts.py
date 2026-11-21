"""Chat routes that serve, preview and inspect session artifacts."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.web._helpers.workspace_artifacts import _safe_upload_name

from ...db import get_db
from ...services.session.artifact_visibility import resolve_user_diagram_artifact
from .._helpers.api_guards import _is_inline_global_artifact_blocked, _require_api_user, _resolve_user_artifact_context
from .._helpers.drawio_preview import render_diagram_preview_html
from .chat_artifact_actions import router as chat_artifact_actions_router

router = APIRouter()


# Session-generated files (HTML, SVG, office previews) never run on the platform's origin: opened directly, the
# browser puts them into an opaque-origin sandbox, so their scripts cannot call the APIs or read storage as the
# viewer. Downloads and the platform's own diagram pages are not affected.
UNTRUSTED_CONTENT_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-downloads",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/chat/api/artifact")
async def chat_artifact_api(
    request: Request,
    path: str,
    download: bool = False,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    if str(path or "").startswith(("diagram://", "artifact://")):
        payload = await resolve_user_diagram_artifact(db, user_id=user.id, path=path)
        xml = str(payload.get("diagram_xml") or "")
        if not xml:
            raise HTTPException(status_code=404, detail="Diagram XML not found")
        title = _safe_upload_name(str(payload.get("title") or "diagram")) + ".drawio"
        headers = {"Content-Disposition": f'attachment; filename="{title}"'} if download else {}
        return Response(content=xml, media_type="application/xml", headers=headers)
    resolved, workspace_root = await _resolve_user_artifact_context(db, user, path)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not download and _is_inline_global_artifact_blocked(resolved, workspace_root):
        raise HTTPException(
            status_code=403,
            detail="Inline rendering is not allowed for global HTML artifacts",
        )
    headers = dict(UNTRUSTED_CONTENT_HEADERS)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{resolved.name}"'
    return FileResponse(resolved, headers=headers)


@router.get("/chat/api/artifact-preview")
async def chat_artifact_preview_api(
    request: Request,
    path: str,
    format: str = "html",
    db: AsyncSession = Depends(get_db),
):
    """Office/HTML artifact preview: structural HTML in-process, or ``format=pdf|png`` rendered by LibreOffice."""
    user = await _require_api_user(request, db)
    from ...services.office.documents import is_office_document, resolve_workspace_path
    from .._helpers.office_preview import office_preview_response

    if str(path or "").startswith(("diagram://", "artifact://")):
        payload = await resolve_user_diagram_artifact(db, user_id=user.id, path=path)
        if not str(payload.get("diagram_xml") or ""):
            raise HTTPException(status_code=404, detail="Diagram XML not found")
        return HTMLResponse(render_diagram_preview_html(payload))

    resolved, workspace_root = await _resolve_user_artifact_context(db, user, path)
    resolved = resolve_workspace_path(workspace_root, str(resolved))
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if _is_inline_global_artifact_blocked(resolved, workspace_root):
        raise HTTPException(
            status_code=403,
            detail="Inline preview is not allowed for global HTML artifacts",
        )
    if resolved.suffix.lower() in {".html", ".htm"}:
        return HTMLResponse(resolved.read_text(encoding="utf-8", errors="replace"), headers=UNTRUSTED_CONTENT_HEADERS)
    if not is_office_document(resolved):
        raise HTTPException(status_code=400, detail="Preview is only available for Office or HTML artifacts")
    response = await office_preview_response(resolved, workspace_root=workspace_root, fmt=format)
    response.headers.update(UNTRUSTED_CONTENT_HEADERS)
    return response


@router.get("/chat/api/artifact-inspect")
async def chat_artifact_inspect_api(
    request: Request,
    path: str,
    mode: str = "stats",
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    from ...services.office.documents import (
        OfficeDocumentError,
        inspect_office_document,
        is_office_document,
        resolve_workspace_path,
    )

    if str(path or "").startswith(("diagram://", "artifact://")):
        payload = await resolve_user_diagram_artifact(db, user_id=user.id, path=path)
        xml = str(payload.get("diagram_xml") or "")
        return JSONResponse(
            {
                "file_name": _safe_upload_name(str(payload.get("title") or "diagram")) + ".drawio",
                "file_type": "drawio",
                "media_type": "application/xml",
                "mode": mode,
                "summary": {
                    "diagram_id": str(payload.get("diagram_id") or ""),
                    "title": str(payload.get("title") or "Diagram"),
                    "xml_bytes": len(xml.encode("utf-8")),
                },
            }
        )

    resolved, workspace_root = await _resolve_user_artifact_context(db, user, path)
    resolved = resolve_workspace_path(workspace_root, str(resolved))
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not is_office_document(resolved):
        raise HTTPException(status_code=400, detail="Inspect is only available for Office artifacts")
    try:
        payload = await inspect_office_document(workspace_root=workspace_root, path=str(resolved), mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OfficeDocumentError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return JSONResponse(payload)


router.include_router(chat_artifact_actions_router)
