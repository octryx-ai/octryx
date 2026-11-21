"""Inbound model gateway: the OpenAI Responses surface for Codex.

Codex's provider ``base_url=<platform>/api/v1/model-gateway/openai/v1`` (``wire_api = "responses"``).
Authentication is the gateway bearer token, exactly as on the Anthropic surface (``model_gateway_inbound``), so
these routes take the raw request; everything else lives in ``services/model_gateway/inbound/openai_service``.

``.../openai/seat`` is the Codex seat's base URL: the session-bound seat credential identifies the session and the
person's own ChatGPT login is forwarded to ChatGPT's Codex backend (``inbound/codex_seat``). With the platform's
``seat_traffic`` on ``device`` (default) the launcher's seat proxy sends the call itself instead: ``.../seat/admit``
runs the same checks and returns the admitted body with a single-use ticket, ``.../seat/report`` records the answer
(``inbound/codex_seat_device``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.model_gateway.inbound.codex_seat import handle_codex_seat_responses
from ...services.model_gateway.inbound.codex_seat_device import handle_codex_seat_admit, handle_codex_seat_report
from ...services.model_gateway.inbound.codex_seat_search import (
    handle_codex_seat_search_admit,
    handle_codex_seat_search_report,
)
from ...services.model_gateway.inbound.openai_service import handle_openai_list_models, handle_responses

MODEL_GATEWAY_OPENAI_PREFIX = "/api/v1/model-gateway/openai"

router = APIRouter(prefix=MODEL_GATEWAY_OPENAI_PREFIX, tags=["model-gateway"])


@router.post("/v1/responses", include_in_schema=False)
async def openai_responses(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_responses(request, db)


@router.get("/v1/models", include_in_schema=False)
async def openai_models(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_openai_list_models(request, db)


@router.post("/seat/responses", include_in_schema=False)
async def openai_codex_seat_responses(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_codex_seat_responses(request, db)


@router.post("/seat/admit", include_in_schema=False)
async def openai_codex_seat_admit(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_codex_seat_admit(request, db)


@router.post("/seat/report", include_in_schema=False)
async def openai_codex_seat_report(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_codex_seat_report(request, db)


@router.post("/seat/search-admit", include_in_schema=False)
async def openai_codex_seat_search_admit(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_codex_seat_search_admit(request, db)


@router.post("/seat/search-report", include_in_schema=False)
async def openai_codex_seat_search_report(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_codex_seat_search_report(request, db)
