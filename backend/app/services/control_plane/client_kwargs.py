"""Provider client kwargs builders for control-plane runtimes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMProvider
from .env_model_access import env_model_access
from .provider_auth import provider_secret_scope


async def _resolve_provider_secret_field(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    field_name: str,
    get_secret_value_func: Any,
) -> str | None:
    tool_name, secret_field_name = provider_secret_scope(provider, field_name)
    value = await get_secret_value_func(db, tool_name=tool_name, field_name=secret_field_name, project_id=None)
    return str(value or "").strip() or None


def _gateway_default_admission() -> Any:
    """Deny-by-default project admission for provider-scoped client kwargs.

    These kwargs are built from a provider row alone, with no session or project
    context, so the resulting client may read the model catalog and readiness but
    must not dispatch. A caller that *does* own a verified project (and therefore a
    server-resolved data classification) replaces this value at the runtime
    boundary (``litellm/runtime_admission.admit_gateway_runtimes``).
    """

    from ..model_gateway.litellm.project_admission import (
        PROJECT_ADMISSION_KWARG,
        UNVERIFIED_PROJECT_ADMISSION,
    )

    return {PROJECT_ADMISSION_KWARG: UNVERIFIED_PROJECT_ADMISSION}


async def _resolve_gateway_virtual_key(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    get_secret_value_func: Any,
) -> str | None:
    """Resolve a gateway virtual key through the Secret Reference boundary only.

    Unlike the generic API-key path this never falls back to a provider-scoped
    secret entry or to settings: a governed gateway key exists as a Secret
    Reference or it does not exist at all.
    """

    secret_ref = str(getattr(provider, "api_key_secret_ref", "") or "").strip()
    if not secret_ref:
        return None
    value = await get_secret_value_func(db, secret_id=secret_ref)
    return str(value or "").strip() or None


def build_provider_client_kwargs(
    provider: LLMProvider | None,
    *,
    settings: Any,
    infer_provider_runtime_func: Any,
    get_provider_auth_mode_func: Any,
) -> dict[str, Any]:
    if not provider:
        # No configured provider: only the environment's declared model access, by its
        # driver id; without one the factory refuses the empty driver.
        access = env_model_access(settings)
        return {
            "provider_name": access.name if access else "",
            "driver": access.driver if access else "",
            "endpoint_url": access.endpoint_url if access else None,
            "api_key": access.api_key if access else None,
            "region": settings.aws_region,
            "role_arn": settings.aws_bedrock_role_arn,
            "auth_mode": "api_key",
        }

    runtime = infer_provider_runtime_func(
        name=provider.name,
        driver=getattr(provider, "driver", None),
        provider_family=getattr(provider, "provider_family", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        auth_mode=provider.auth_mode,
    )
    kwargs: dict[str, Any] = {
        "provider_name": provider.name,
        "driver": runtime["driver"],
        "provider_family": runtime["provider_family"],
        "runtime_kind": runtime["runtime_kind"],
        "profile_name": getattr(provider, "profile_name", None),
        "endpoint_url": getattr(provider, "endpoint_url", None),
        "binary_path": getattr(provider, "binary_path", None),
        "config_json": getattr(provider, "config_json", None),
        "capabilities_json": getattr(provider, "capabilities_json", None),
        "region": provider.aws_region or settings.aws_region,
        "role_arn": provider.aws_role_arn or settings.aws_bedrock_role_arn,
        "api_key": None,
        "auth_mode": get_provider_auth_mode_func(provider),
    }
    if runtime["driver"] == "copilot_api":
        kwargs["copilot_token"] = None
    if runtime["driver"] == "litellm_gateway":
        kwargs.update(_gateway_default_admission())
    if runtime["driver"] == "gemini_api":
        kwargs["google_access_token"] = None
        kwargs["google_project_id"] = None
    return kwargs


async def build_provider_client_kwargs_async(
    db: AsyncSession,
    provider: LLMProvider | None,
    *,
    build_provider_client_kwargs_func: Any,
    infer_provider_runtime_func: Any,
    ensure_provider_local_runtime_ready_func: Any,
    build_copilot_access_token_func: Any,
    build_google_access_token_func: Any,
    resolve_provider_api_key_func: Any,
    get_secret_value_func: Any,
    set_secret_value_func: Any,
    settings: Any,
) -> dict[str, Any]:
    kwargs = build_provider_client_kwargs_func(provider)
    if not provider:
        return kwargs

    runtime = infer_provider_runtime_func(
        name=provider.name,
        driver=getattr(provider, "driver", None),
        provider_family=getattr(provider, "provider_family", None),
        runtime_kind=getattr(provider, "runtime_kind", None),
        auth_mode=provider.auth_mode,
    )

    if runtime["driver"] == "ollama":
        await _require_local_runtime_ready(provider, runtime, ensure_provider_local_runtime_ready_func)
        kwargs["api_key"] = None
    elif runtime["driver"] == "copilot_api":
        await _apply_copilot_token(
            db,
            provider,
            kwargs,
            build_copilot_access_token_func=build_copilot_access_token_func,
            resolve_provider_api_key_func=resolve_provider_api_key_func,
            get_secret_value_func=get_secret_value_func,
            set_secret_value_func=set_secret_value_func,
            settings=settings,
        )
    elif runtime["driver"] == "bedrock_api":
        await _apply_bedrock_credentials(db, provider, kwargs, get_secret_value_func=get_secret_value_func)
    elif runtime["driver"] == "litellm_gateway":
        kwargs["api_key"] = await _resolve_gateway_virtual_key(
            db,
            provider,
            get_secret_value_func=get_secret_value_func,
        )
    elif runtime["driver"] == "gemini_api":
        await _apply_gemini_credentials(
            db,
            provider,
            kwargs,
            build_google_access_token_func=build_google_access_token_func,
            resolve_provider_api_key_func=resolve_provider_api_key_func,
            get_secret_value_func=get_secret_value_func,
        )
    else:
        kwargs["api_key"] = await resolve_provider_api_key_func(db, provider)
    return kwargs


async def _require_local_runtime_ready(
    provider: LLMProvider, runtime: dict[str, Any], ensure_provider_local_runtime_ready_func: Any
) -> None:
    runtime_state = await ensure_provider_local_runtime_ready_func(provider)
    if runtime_state["status"] != "ready":
        raise RuntimeError(
            f"Local runtime '{runtime['driver']}' is not ready: "
            f"{runtime_state.get('error') or runtime_state['status']}"
        )


async def _apply_copilot_token(
    db: AsyncSession,
    provider: LLMProvider,
    kwargs: dict[str, Any],
    *,
    build_copilot_access_token_func: Any,
    resolve_provider_api_key_func: Any,
    get_secret_value_func: Any,
    set_secret_value_func: Any,
    settings: Any,
) -> None:
    if kwargs["auth_mode"] == "oauth":
        kwargs["copilot_token"] = await build_copilot_access_token_func(
            db,
            provider=provider,
            get_secret_value_func=get_secret_value_func,
            set_secret_value_func=set_secret_value_func,
        )
    elif kwargs["auth_mode"] == "api_key":
        kwargs["copilot_token"] = await resolve_provider_api_key_func(db, provider) or settings.copilot_token


async def _apply_bedrock_credentials(
    db: AsyncSession,
    provider: LLMProvider,
    kwargs: dict[str, Any],
    *,
    get_secret_value_func: Any,
) -> None:
    # Resolved one after the other, in this order, as each is a separate secret lookup.
    for field_name in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        kwargs[field_name] = await _resolve_provider_secret_field(
            db,
            provider,
            field_name=field_name,
            get_secret_value_func=get_secret_value_func,
        )


async def _apply_gemini_credentials(
    db: AsyncSession,
    provider: LLMProvider,
    kwargs: dict[str, Any],
    *,
    build_google_access_token_func: Any,
    resolve_provider_api_key_func: Any,
    get_secret_value_func: Any,
) -> None:
    if kwargs["auth_mode"] == "oauth":
        access_token, project_id = await build_google_access_token_func(
            db,
            provider=provider,
            get_secret_value_func=get_secret_value_func,
        )
        kwargs["google_access_token"] = access_token
        kwargs["google_project_id"] = project_id
    else:
        kwargs["api_key"] = await resolve_provider_api_key_func(db, provider)
