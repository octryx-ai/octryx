"""The Office part of ``/chat/api/artifact-preview``: structural HTML in-process, or a LibreOffice render."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from app.services.office.render_sandbox import RENDER_FORMATS

from ...services.office.documents import OfficeDocumentError, render_office_preview_html
from ...services.office.render import (
    STATE_STATUS,
    OfficePreviewUnavailableError,
    OfficeRenderError,
    render_office_document,
    render_state_page,
)


async def office_preview_response(resolved: Path, *, workspace_root: Path, fmt: str) -> Response:
    if fmt in RENDER_FORMATS:
        try:
            rendered = await render_office_document(resolved, fmt)
        except (OfficePreviewUnavailableError, OfficeRenderError) as exc:
            return HTMLResponse(render_state_page(exc.code), status_code=STATE_STATUS.get(exc.code, 422))
        return Response(content=rendered, media_type=RENDER_FORMATS[fmt])
    if fmt != "html":
        raise HTTPException(status_code=400, detail="format must be html, pdf or png")
    try:
        html = await render_office_preview_html(workspace_root=workspace_root, path=str(resolved))
    except OfficeDocumentError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return HTMLResponse(html)


__all__ = ["office_preview_response"]
