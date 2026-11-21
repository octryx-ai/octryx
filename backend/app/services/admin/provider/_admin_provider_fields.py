"""Field mapping for provider create and update requests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....agent.providers import infer_provider_runtime
from ....models import LLMProvider
from ...provider.oauth_config_bridge import read_oauth_metadata, write_oauth_metadata
from ...provider_runtime_config import apply_provider_runtime_defaults
from ._admin_provider_secrets import (
    BEDROCK_STATIC_CREDENTIAL_FIELDS,
    _store_provider_api_key,
    _store_provider_secrets,
    store_google_client_secret,
)


def initial_gemini_auth(runtime: dict[str, Any], payload: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    auth_mode = runtime["auth_mode"]
    auth_metadata: dict[str, Any] = {}
    if runtime["driver"] == "gemini_api":
        auth_mode = auth_mode if auth_mode in {"api_key", "oauth"} else "api_key"
        auth_metadata = {
            "oauth_client_id": str(payload.get("google_oauth_client_id") or "").strip(),
            "google_cloud_project": str(payload.get("google_cloud_project") or "").strip(),
        }
    return auth_mode, auth_metadata


def build_provider_row(payload: dict[str, Any], *, runtime: dict[str, Any], auth_mode: Any) -> LLMProvider:
    return LLMProvider(
        id=str(uuid.uuid4()),
        name=runtime["name"],
        provider_family=runtime["provider_family"],
        driver=runtime["driver"],
        runtime_kind=runtime["runtime_kind"],
        display_name=str(payload.get("display_name") or runtime["name"]),
        profile_name=str(payload.get("profile_name") or "").strip() or None,
        endpoint_url=str(payload.get("endpoint_url") or "").strip() or None,
        binary_path=str(payload.get("binary_path") or "").strip() or None,
        auth_mode=auth_mode,
        config_json=(payload.get("config_json") if isinstance(payload.get("config_json"), dict) else None),
        capabilities_json=(
            payload.get("capabilities_json") if isinstance(payload.get("capabilities_json"), dict) else None
        ),
        aws_region=payload.get("aws_region") or None,
        aws_role_arn=payload.get("aws_role_arn") or None,
        bootstrap_role=str(payload.get("bootstrap_role") or "").strip() or None,
        is_global=bool(payload.get("is_global", True)),
    )


def apply_runtime_defaults_to_provider(provider: LLMProvider, runtime: dict[str, Any]) -> None:
    config_json, capabilities_json = apply_provider_runtime_defaults(
        provider,
        runtime=runtime,
        config_json=provider.config_json if isinstance(provider.config_json, dict) else {},
        capabilities_json=provider.capabilities_json if isinstance(provider.capabilities_json, dict) else {},
    )
    provider.config_json = config_json or None
    provider.capabilities_json = capabilities_json or None


def apply_descriptive_fields(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("display_name") is not None:
        provider.display_name = str(payload["display_name"])
    if payload.get("profile_name") is not None:
        provider.profile_name = str(payload.get("profile_name") or "").strip() or None
    if payload.get("endpoint_url") is not None:
        provider.endpoint_url = str(payload.get("endpoint_url") or "").strip() or None
    if payload.get("binary_path") is not None:
        provider.binary_path = str(payload.get("binary_path") or "").strip() or None
    if payload.get("bootstrap_role") is not None:
        provider.bootstrap_role = str(payload.get("bootstrap_role") or "").strip() or None
    if payload.get("config_json") is not None and isinstance(payload.get("config_json"), dict):
        provider.config_json = dict(payload["config_json"])
    if payload.get("capabilities_json") is not None and isinstance(payload.get("capabilities_json"), dict):
        provider.capabilities_json = dict(payload["capabilities_json"])


def apply_runtime_fields(provider: LLMProvider, payload: dict[str, Any]) -> dict[str, Any]:
    if (
        payload.get("driver") is not None
        or payload.get("provider_family") is not None
        or payload.get("runtime_kind") is not None
    ):
        runtime = infer_provider_runtime(
            name=provider.name,
            driver=payload.get("driver") or provider.driver,
            provider_family=payload.get("provider_family") or provider.provider_family,
            runtime_kind=payload.get("runtime_kind") or provider.runtime_kind,
            auth_mode=payload.get("auth_mode") or provider.auth_mode,
        )
        if payload.get("name") is not None:
            provider.name = str(payload.get("name") or "").strip().lower() or runtime["name"]
        provider.provider_family = runtime["provider_family"]
        provider.driver = runtime["driver"]
        provider.runtime_kind = runtime["runtime_kind"]
        return runtime
    return infer_provider_runtime(
        name=provider.name,
        driver=provider.driver,
        provider_family=provider.provider_family,
        runtime_kind=provider.runtime_kind,
        auth_mode=provider.auth_mode,
    )


def apply_auth_mode(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("auth_mode") is None:
        return
    raw_auth_mode = str(payload.get("auth_mode") or "").strip().lower()
    driver = infer_provider_runtime(driver=provider.driver)["driver"]
    if driver == "gemini_api":
        provider.auth_mode = raw_auth_mode if raw_auth_mode in {"api_key", "oauth"} else "api_key"
    elif driver == "copilot_api":
        provider.auth_mode = (
            raw_auth_mode if raw_auth_mode in {"api_key", "auth_session", "oauth"} else "auth_session"
        )
    elif driver == "bedrock_api":
        provider.auth_mode = (
            raw_auth_mode if raw_auth_mode in {"aws_role", "aws_credentials", "environment"} else "aws_role"
        )
    elif driver == "ollama":
        provider.auth_mode = "none"
    elif infer_provider_runtime(driver=provider.driver)["runtime_kind"] == "cli":
        provider.auth_mode = raw_auth_mode or "profile"


def apply_aws_and_active_fields(provider: LLMProvider, payload: dict[str, Any]) -> None:
    if payload.get("aws_region") is not None:
        provider.aws_region = str(payload["aws_region"]) or None
    if payload.get("aws_role_arn") is not None:
        provider.aws_role_arn = str(payload["aws_role_arn"]) or None
    if payload.get("is_active") is not None:
        provider.is_active = bool(payload["is_active"])


async def store_updated_driver_credentials(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    payload: dict[str, Any],
    set_secret_value_func: Callable[..., Any] | None,
) -> None:
    current_driver = infer_provider_runtime(driver=provider.driver)["driver"]
    if current_driver == "bedrock_api":
        await _store_provider_secrets(
            db,
            provider,
            payload=payload,
            field_names=BEDROCK_STATIC_CREDENTIAL_FIELDS,
            set_secret_value_func=set_secret_value_func,
        )
    if current_driver == "gemini_api":
        meta = await read_oauth_metadata(db, provider)
        if payload.get("google_oauth_client_id") is not None:
            meta["oauth_client_id"] = str(payload.get("google_oauth_client_id") or "").strip()
        if payload.get("google_cloud_project") is not None:
            meta["google_cloud_project"] = str(payload.get("google_cloud_project") or "").strip()
        await write_oauth_metadata(db, provider, meta)
        google_client_secret = str(payload.get("google_oauth_client_secret") or "").strip()
        if google_client_secret and set_secret_value_func:
            await store_google_client_secret(
                db,
                provider,
                google_client_secret=google_client_secret,
                set_secret_value_func=set_secret_value_func,
            )


async def store_created_provider_credentials(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    payload: dict[str, Any],
    runtime: dict[str, Any],
    auth_metadata: dict[str, Any],
    set_secret_value_func: Callable[..., Any] | None,
) -> None:
    if auth_metadata:
        # Persist the initial gemini OAuth config into provider_oauth_config.
        await write_oauth_metadata(db, provider, auth_metadata)
    if payload.get("api_key") is not None:
        await _store_provider_api_key(
            db,
            provider,
            raw_value=payload.get("api_key"),
            set_secret_value_func=set_secret_value_func,
        )
    if runtime["driver"] == "bedrock_api":
        await _store_provider_secrets(
            db,
            provider,
            payload=payload,
            field_names=BEDROCK_STATIC_CREDENTIAL_FIELDS,
            set_secret_value_func=set_secret_value_func,
        )
    google_client_secret = str(payload.get("google_oauth_client_secret") or "").strip()
    if runtime["driver"] == "gemini_api" and google_client_secret and set_secret_value_func:
        await store_google_client_secret(
            db,
            provider,
            google_client_secret=google_client_secret,
            set_secret_value_func=set_secret_value_func,
        )
