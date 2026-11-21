"""Admin panel routes for the visual Agent Designer.

The designer runs as a static, credential-free artifact on its own origin inside an
iframe. The admin host page calls these routes with its normal session (panel
same-origin policy applies) and relays documents to the frame by ``postMessage``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.services.agent_designer.document_model import DesignerDocumentError
from app.services.agent_designer.service import (
    load_designer_document,
    publish_displayed_revision,
    save_designer_document,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


def designer_origin(raw: str | None) -> str | None:
    """Return the configured origin if it is exactly ``scheme://host[:port]``."""
    value = str(raw or "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    # Browsers report an origin without its scheme's default port; so must we, or no message matches.
    if port == {"http": 80, "https": 443}[parts.scheme]:
        port = None
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


@router.get("/chat/api/panel/agent-designer/config")
async def panel_agent_designer_config(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    origin = designer_origin(get_settings().agent_designer_origin)
    if origin is None:
        return JSONResponse({"state": "needs_configuration", "origin": None})
    return JSONResponse({"state": "ready", "origin": origin})


@router.get("/chat/api/panel/agents/{agent_id}/designer-document")
async def panel_get_designer_document(agent_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await load_designer_document(db, user_id=user.id, agent_id=agent_id))


@router.put("/chat/api/panel/agents/{agent_id}/designer-document")
async def panel_save_designer_document(
    agent_id: str,
    request: Request,
    document: Any = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    try:
        return JSONResponse(await save_designer_document(db, user_id=user.id, agent_id=agent_id, document=document))
    except DesignerDocumentError as exc:
        return JSONResponse(
            status_code=422,
            content={"state": "invalid_document", "issues": [issue.as_dict() for issue in exc.issues]},
        )


@router.post("/chat/api/panel/agents/{agent_id}/designer-document/publish")
async def panel_publish_designer_revision(
    agent_id: str,
    request: Request,
    revision_id: str = Body(..., embed=True, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await publish_displayed_revision(db, user_id=user.id, agent_id=agent_id, revision_id=revision_id)
    )
