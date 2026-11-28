"""Inbound model gateway: the OpenAI Responses surface for Codex."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.model_gateway.inbound.codex_seat import handle_codex_seat_responses
from ....services.model_gateway.inbound.openai_service import handle_openai_list_models, handle_responses

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

