"""Admin edits of single provider models: manual registration and field updates."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMModel, LLMProvider
from ..governance.admin_config_audit_service import record_admin_config_audit
from ._admin_provider_snapshots import _model_audit_snapshot
from .model_price_edit import apply_model_price_edit, model_price_snapshot
from .model_price_edit import normalize_optional_model_price as _normalize_optional_model_price


def _apply_model_flags(model: LLMModel, payload: dict[str, Any]) -> None:
    if payload.get("is_active") is not None:
        model.is_active = bool(payload["is_active"])
    if payload.get("display_name") is not None:
        model.display_name = str(payload["display_name"])
    if payload.get("supports_tools") is not None:
        model.supports_tools = bool(payload["supports_tools"])
    if payload.get("supports_vision") is not None:
        model.supports_vision = bool(payload["supports_vision"])


def _apply_model_output_budget(model: LLMModel, payload: dict[str, Any]) -> None:
    if "max_tokens_per_request" in payload:
        raw_output_budget = payload.get("max_tokens_per_request")
        if raw_output_budget in ("", 0, "0", None):
            model.max_tokens_per_request = None
        else:
            budget = int(raw_output_budget)
            if budget < 256:
                raise HTTPException(status_code=400, detail="max_tokens_per_request must be at least 256")
            model.max_tokens_per_request = budget


async def update_model(
    db: AsyncSession,
    *,
    provider_id: str,
    model_id: str,
    payload: dict[str, Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    model = (
        await db.execute(select(LLMModel).where(LLMModel.id == model_id, LLMModel.provider_id == provider_id))
    ).scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    before = _model_audit_snapshot(model)
    _apply_model_flags(model, payload)
    _apply_model_output_budget(model, payload)
    # A governed cost source owns its price; see ``model_price_edit``.
    apply_model_price_edit(model, payload)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.model.updated",
        resource_type="provider_model",
        resource_id=model.id,
        project_id=None,
        before=before,
        after=_model_audit_snapshot(model),
        details={
            "operation": "update_model",
            "provider_id": provider_id,
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return {
        "id": model.id,
        "model_id": model.model_id,
        "is_active": model.is_active,
        "display_name": model.display_name or model.model_id,
        "max_tokens_per_request": model.max_tokens_per_request,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        **model_price_snapshot(model),
    }


def _new_model_max_tokens_per_request(payload: dict[str, Any]) -> int | None:
    max_tokens_per_request = None
    raw_output_budget = payload.get("max_tokens_per_request")
    if raw_output_budget not in ("", 0, "0", None):
        max_tokens_per_request = int(raw_output_budget)
        if max_tokens_per_request < 256:
            raise HTTPException(status_code=400, detail="max_tokens_per_request must be at least 256")
    return max_tokens_per_request


def _added_model_payload(model: LLMModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "is_active": True,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        "context_length": model.context_length,
        "max_tokens_per_request": model.max_tokens_per_request,
        "pricing_input": model.pricing_input,
        "pricing_output": model.pricing_output,
    }


async def add_model(
    db: AsyncSession,
    *,
    provider_id: str,
    payload: dict[str, Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    model_id_val = str(payload.get("model_id") or "").strip()
    if not model_id_val:
        raise HTTPException(status_code=400, detail="model_id is required")
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    existing = (
        await db.execute(select(LLMModel).where(LLMModel.provider_id == provider_id, LLMModel.model_id == model_id_val))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Model already registered")
    max_tokens_per_request = _new_model_max_tokens_per_request(payload)
    pricing_input = _normalize_optional_model_price(payload.get("pricing_input"), field_name="pricing_input")
    pricing_output = _normalize_optional_model_price(payload.get("pricing_output"), field_name="pricing_output")
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider_id,
        model_id=model_id_val,
        display_name=str(payload.get("display_name") or model_id_val),
        context_length=payload.get("context_length"),
        max_tokens_per_request=max_tokens_per_request,
        pricing_input=pricing_input,
        pricing_output=pricing_output,
        supports_tools=bool(payload.get("supports_tools", True)),
        supports_vision=bool(payload.get("supports_vision", False)),
        supports_streaming=True,
        is_active=True,
    )
    db.add(model)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.model.created",
        resource_type="provider_model",
        resource_id=model.id,
        project_id=None,
        before=None,
        after=_model_audit_snapshot(model),
        details={
            "operation": "add_model",
            "provider_id": provider_id,
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    return _added_model_payload(model)
