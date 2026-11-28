"""Inbound model gateway: the Anthropic Messages surface for ``octryx-claude``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.model_gateway.inbound.model_routes import handle_list_models, handle_seat_list_models
from ....services.model_gateway.inbound.seat import handle_seat_count_tokens, handle_seat_messages
from ....services.model_gateway.inbound.service import handle_count_tokens, handle_messages

MODEL_GATEWAY_INBOUND_PREFIX = "/api/v1/model-gateway/anthropic"

router = APIRouter(prefix=MODEL_GATEWAY_INBOUND_PREFIX, tags=["model-gateway"])


@router.post("/v1/messages", include_in_schema=False)
async def anthropic_messages(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_messages(request, db)


@router.post("/v1/messages/count_tokens", include_in_schema=False)
async def anthropic_count_tokens(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_count_tokens(request, db)


@router.get("/v1/models", include_in_schema=False)
async def anthropic_models(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_list_models(request, db)


@router.get("/seat/v1/models", include_in_schema=False)
async def anthropic_seat_models(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_seat_list_models(request, db)


@router.post("/seat/v1/messages", include_in_schema=False)
async def anthropic_seat_messages(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_seat_messages(request, db)


@router.post("/seat/v1/messages/count_tokens", include_in_schema=False)
async def anthropic_seat_count_tokens(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    return await handle_seat_count_tokens(request, db)
