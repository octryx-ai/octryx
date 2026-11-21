"""Audit snapshots and the public model payload for provider administration."""

from __future__ import annotations

from typing import Any

from ....models import LLMModel, LLMProvider
from ....models.runtime.provider_oauth_config import oauth_metadata_from_provider
from .model_price_edit import model_price_snapshot


def _provider_audit_snapshot(provider: LLMProvider | None) -> dict[str, Any]:
    if provider is None:
        return {}
    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name,
        "provider_family": provider.provider_family,
        "driver": provider.driver,
        "runtime_kind": provider.runtime_kind,
        "profile_name": provider.profile_name,
        "endpoint_url": provider.endpoint_url,
        "binary_path": provider.binary_path,
        "api_key_secret_ref": provider.api_key_secret_ref,
        "auth_mode": provider.auth_mode,
        "auth_metadata_json": oauth_metadata_from_provider(provider) or None,
        "config_json": provider.config_json,
        "capabilities_json": provider.capabilities_json,
        "aws_region": provider.aws_region,
        "aws_role_arn": provider.aws_role_arn,
        "bootstrap_role": provider.bootstrap_role,
        "is_global": provider.is_global,
        "is_active": provider.is_active,
    }


def _model_audit_snapshot(model: LLMModel | None) -> dict[str, Any]:
    if model is None:
        return {}
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "context_length": model.context_length,
        "planner_context_budget": model.planner_context_budget,
        "max_tokens_per_request": model.max_tokens_per_request,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        "supports_streaming": model.supports_streaming,
        **model_price_snapshot(model),
        "is_active": model.is_active,
    }


def _model_inventory_audit_snapshot(models: list[LLMModel]) -> dict[str, Any]:
    return {
        "model_count": len(models),
        "models": [
            {
                "id": model.id,
                "model_id": model.model_id,
                "display_name": model.display_name,
                "is_active": model.is_active,
            }
            for model in models
        ],
    }


def serialize_model(model: LLMModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "model_id": model.model_id,
        "display_name": model.display_name or model.model_id,
        "context_length": model.context_length,
        "planner_context_budget": model.planner_context_budget,
        "max_tokens_per_request": model.max_tokens_per_request,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        "supports_streaming": model.supports_streaming,
        **model_price_snapshot(model),
        "is_active": model.is_active,
        "last_synced_at": model.last_synced_at.isoformat() if model.last_synced_at else None,
    }
