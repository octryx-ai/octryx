"""Server-rendered PNG images for diagram artifacts (drawio CLI). Without a drawio CLI the endpoint answers 503
``renderer_unavailable`` and the card falls back to the embed."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.diagram_export_service import (
    ALLOWED_SCALES,
    DiagramRenderError,
    DiagramRendererUnavailableError,
    render_diagram_png,
)
from ...services.error_facts import error_facts, error_text
from ...services.session.artifact_visibility import resolve_user_diagram_artifact
from .._helpers.api_guards import _require_api_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/chat/api/artifact-image")
async def chat_artifact_image_api(
    request: Request,
    path: str,
    scale: int = 2,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    if not str(path or "").startswith(("diagram://", "artifact://")):
        raise HTTPException(status_code=400, detail="Image rendering is only available for diagram artifacts")
    if scale not in ALLOWED_SCALES:
        raise HTTPException(status_code=400, detail=f"Unsupported scale; allowed: {list(ALLOWED_SCALES)}")

    payload = await resolve_user_diagram_artifact(db, user_id=user.id, path=path)
    xml = str(payload.get("diagram_xml") or "")
    if not xml:
        raise HTTPException(status_code=404, detail="Diagram XML not found")
    diagram_id = str(payload.get("diagram_id") or "").strip() or path.split("://", 1)[-1]

    try:
        png = await asyncio.to_thread(
            render_diagram_png, diagram_id=diagram_id, diagram_xml=xml, scale=scale
        )
    except DiagramRendererUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DiagramRenderError as exc:
        # The render error can carry drawio CLI stderr and OS error text: only fixed facts leave.
        logger.warning(
            "diagram_image.render_failed",
            extra={"diagram_id": diagram_id, **error_facts("diagram_render_failed", exc)},
        )
        raise HTTPException(
            status_code=500,
            detail=f"Diagram rendering failed. {error_text('diagram_render_failed', exc)}",
        ) from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
