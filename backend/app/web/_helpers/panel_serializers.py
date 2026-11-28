"""Panel data serializer helpers."""

from datetime import date

from fastapi import HTTPException

from ...agent.providers import infer_provider_runtime
from ...models import (
    BuiltInToolConfig,
    ConnectorPolicy,
    ControlPlaneRuntimeTarget,
    LLMModel,
    LLMProvider,
)
from ...models.runtime.provider_oauth_config import oauth_metadata_from_provider
from ...services.connector_policy import normalize_connector_policy
from ...services.connector_test_service import CONNECTOR_TESTS
from ...services.control_plane.runtime_temperature import serialize_target_temperature
from ...services.provider import (
    provider_public_credential_marker,
    provider_secret_is_configured,
    redact_provider_public_metadata,
    resolve_provider_readiness,
)
from ...services.tool_config import (
    TOOL_CONFIG_PRESETS,
    resolve_connector_tools,
)

__all__ = [
    "_serialize_provider",
    "_serialize_runtime_target",
    "_serialize_connector",
    "_parse_optional_iso_date",
]


def _serialize_provider(p: LLMProvider, model_count: int = 0, active_model_count: int = 0) -> dict:
    meta = oauth_metadata_from_provider(p)
    has_provider_secret = provider_secret_is_configured(
        secret_ref=getattr(p, "api_key_secret_ref", None),
    )
    has_credentials = has_provider_secret or bool(meta.get("login"))
    has_aws_static_credentials = bool(meta.get("aws_static_credentials_configured"))
    runtime = infer_provider_runtime(
        name=p.name,
        driver=getattr(p, "driver", None),
        provider_family=getattr(p, "provider_family", None),
        runtime_kind=getattr(p, "runtime_kind", None),
        auth_mode=p.auth_mode,
    )
    readiness = resolve_provider_readiness(p)
    return {
        "id": p.id,
        "name": p.name,
        "provider_family": runtime["provider_family"],
        "driver": runtime["driver"],
        "runtime_kind": runtime["runtime_kind"],
        "display_name": p.display_name or p.name,
        "profile_name": getattr(p, "profile_name", "") or "",
        "endpoint_url": getattr(p, "endpoint_url", "") or "",
        "binary_path": getattr(p, "binary_path", "") or "",
        "is_active": p.is_active,
        "is_global": p.is_global,
        "has_api_key": has_credentials or has_aws_static_credentials,
        "api_key_masked": provider_public_credential_marker(
            configured=has_provider_secret or has_aws_static_credentials,
        ),
        "auth_mode": p.auth_mode or "api_key",
        "auth_login": meta.get("login", ""),
        "auth_name": meta.get("name", ""),
        "auth_host": meta.get("host", ""),
        "google_cloud_project": meta.get("google_cloud_project", ""),
        "google_oauth_client_id": meta.get("oauth_client_id", ""),
        "google_oauth_client_configured": bool(meta.get("oauth_client_id")),
        "aws_region": p.aws_region or "",
        "aws_role_arn": p.aws_role_arn or "",
        "aws_static_credentials_configured": has_aws_static_credentials,
        "config_json": redact_provider_public_metadata(p.config_json) if isinstance(p.config_json, dict) else {},
        "capabilities_json": (
            redact_provider_public_metadata(p.capabilities_json) if isinstance(p.capabilities_json, dict) else {}
        ),
        "bootstrap_role": getattr(p, "bootstrap_role", "") or "",
        "health_status": getattr(p, "health_status", "") or "",
        "readiness_status": readiness["status"],
        "readiness_reason": readiness["reason"],
        "readiness": readiness,
        "last_health_check_at": p.last_health_check_at.isoformat() if getattr(p, "last_health_check_at", None) else "",
        "last_health_error": getattr(p, "last_health_error", "") or "",
        "model_count": model_count,
        "active_model_count": active_model_count,
        "created_at": p.created_at.isoformat() if p.created_at else "",
    }


def _serialize_runtime_target(
    target: ControlPlaneRuntimeTarget,
    provider: LLMProvider | None,
    model: LLMModel | None = None,
) -> dict:
    return {
        "id": target.id,
        "provider_id": target.provider_id,
        "provider_name": provider.name if provider else "unknown",
        "provider_display_name": provider.display_name or (provider.name if provider else "Unknown"),
        "model_id": target.model_id,
        "supports_tools": bool(model.supports_tools) if model else None,
        "supports_vision": bool(model.supports_vision) if model else None,
        "priority": target.priority,
        "is_active": target.is_active,
        "use_case_tags": target.use_case_tags,
        "capability_tags": target.capability_tags,
        "accepts_temperature": target.accepts_temperature,
        **serialize_target_temperature(target, provider, model),
    }


def _serialize_connector(
    tool_name: str,
    entry: BuiltInToolConfig | None,
    policy_entry: ConnectorPolicy | None,
) -> dict:
    preset = TOOL_CONFIG_PRESETS.get(tool_name, {})
    secret_fields = preset.get("secret_fields", [])
    config = dict(entry.config) if entry and entry.config else {}
    policy = normalize_connector_policy(policy_entry.policy if policy_entry and policy_entry.policy else {})
    public_fields: dict[str, object] = {}
    for key, val in config.items():
        if key in secret_fields:
            continue  # never expose raw secrets
        if key.endswith("_secret_ref"):
            continue
        public_fields[key] = val
    secret_status: dict[str, bool] = {f: bool(config.get(f) or config.get(f"{f}_secret_ref")) for f in secret_fields}
    configured = bool(entry and (entry.config or not preset.get("fields")))
    return {
        "tool_name": tool_name,
        "label": preset.get("label", tool_name.title()),
        "description": preset.get("description", ""),
        "fields": preset.get("fields", []),
        "secret_fields": secret_fields,
        # Derived from the registered tests, so every connector with a test shows the button.
        "supports_test": tool_name in CONNECTOR_TESTS,
        "builtin_tools": preset.get("tools", []),
        "tools": resolve_connector_tools(tool_name, policy),
        "tool_policy": policy,
        "is_active": entry.is_active if entry else False,
        "policy_active": policy_entry.is_active if policy_entry else True,
        "configured": configured,
        "public_fields": public_fields,
        "secret_status": secret_status,
        "db_id": entry.id if entry else None,
        "policy_id": policy_entry.id if policy_entry else None,
    }


def _parse_optional_iso_date(value: str | None, *, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc
