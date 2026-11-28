"""Model routes of the bundled LiteLLM: the route and its credential live in LiteLLM, the alias (data class, context,
price, tools) in the bundled provider's gateway config, so the model list, clearance and defaults stay as they are."""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import LLMModel, LLMProvider
from .bundled_litellm import PROVIDER_NAME, bundled_url, master_key
from .litellm.alias_catalog import DATA_POLICY_CLASSES, GATEWAY_CONFIG_KEY

_TIMEOUT = 20.0
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
TYPE_KEY = "octryx_provider_type"


@dataclass(frozen=True, slots=True)
class ProviderType:
    prefix: str
    fields: tuple[str, ...]
    required: tuple[str, ...]


# What LiteLLM needs per upstream, nothing more (``litellm_params``).
PROVIDER_TYPES: dict[str, ProviderType] = {
    "anthropic": ProviderType("anthropic", ("api_key",), ("api_key",)),
    "openai": ProviderType("openai", ("api_key",), ("api_key",)),
    "bedrock": ProviderType("bedrock", ("aws_region_name", "aws_access_key_id", "aws_secret_access_key",
                                        "aws_session_token"), ("aws_region_name",)),
    "azure": ProviderType("azure", ("api_base", "api_key", "api_version"), ("api_base", "api_key")),
    "gemini": ProviderType("gemini", ("api_key",), ("api_key",)),
    "openrouter": ProviderType("openrouter", ("api_key",), ("api_key",)),
    "ollama": ProviderType("ollama_chat", ("api_base",), ("api_base",)),
    "openai_compatible": ProviderType("openai", ("api_base", "api_key"), ("api_base",)),
}
# Shown back to the admin; every other credential field is write-only.
_VISIBLE_FIELDS = frozenset({"api_base", "aws_region_name", "api_version"})


def _refused(detail: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


async def _litellm(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    url, key = bundled_url(), master_key()
    if not url or not key:
        raise _refused("The bundled LiteLLM is not part of this installation.", 409)
    async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
        response = await client.request(method, f"{url}{path}", json=body,
                                        headers={"Authorization": f"Bearer {key}"})
    if response.status_code >= 400:
        # LiteLLM's error text may echo the request; only the status reaches the admin.
        raise _refused(f"LiteLLM refused the change ({response.status_code}).", 502)
    return response.json()


async def _bundled_provider(db: AsyncSession) -> LLMProvider:
    provider = (await db.execute(select(LLMProvider).where(LLMProvider.name == PROVIDER_NAME))).scalar_one_or_none()
    if provider is None:
        raise _refused("The bundled LiteLLM provider is not registered yet; restart the platform.", 409)
    return provider


def _aliases(provider: LLMProvider) -> dict[str, Any]:
    return dict(dict((provider.config_json or {}).get(GATEWAY_CONFIG_KEY) or {}).get("aliases") or {})


def _set_aliases(provider: LLMProvider, aliases: dict[str, Any]) -> None:
    config = copy.deepcopy(dict(provider.config_json or {}))
    config.setdefault(GATEWAY_CONFIG_KEY, {})["aliases"] = aliases
    provider.config_json = config
    flag_modified(provider, "config_json")


async def _deployments() -> dict[str, dict[str, Any]]:
    data = (await _litellm("GET", "/model/info")).get("data") or []
    return {str(item.get("model_name")): item for item in data if isinstance(item, dict)}


def _route_view(alias: str, entry: dict[str, Any] | None, deployment: dict[str, Any] | None) -> dict[str, Any]:
    params = dict((deployment or {}).get("litellm_params") or {})
    info = dict((deployment or {}).get("model_info") or {})
    kind = str(info.get(TYPE_KEY) or "")
    model = str(params.get("model") or "")
    prefix = PROVIDER_TYPES[kind].prefix + "/" if kind in PROVIDER_TYPES else ""
    entry = entry or {}
    cost = dict(entry.get("cost") or {})
    state = "ok" if entry and deployment else "needs_configuration"
    return {
        "alias": alias, "provider_type": kind, "model": model.removeprefix(prefix),
        "settings": {key: params[key] for key in _VISIBLE_FIELDS if params.get(key)},
        "data_policy_class": entry.get("data_policy_class"), "context_limit": entry.get("context_limit"),
        "input_per_million_usd": cost.get("input_per_million_usd"),
        "output_per_million_usd": cost.get("output_per_million_usd"),
        "tools": bool(dict(entry.get("capabilities") or {}).get("tools")), "state": state,
        "problem": "" if state == "ok" else ("no route in LiteLLM" if entry else "no alias in Octryx"),
    }


async def list_routes(db: AsyncSession) -> dict[str, Any]:
    provider = await _bundled_provider(db)
    aliases, deployments = _aliases(provider), await _deployments()
    names = sorted({*aliases, *deployments})
    return {"routes": [_route_view(name, aliases.get(name), deployments.get(name)) for name in names],
            "provider_types": {name: {"fields": list(kind.fields), "required": list(kind.required)}
                               for name, kind in PROVIDER_TYPES.items()},
            "data_policy_classes": sorted(DATA_POLICY_CLASSES)}


def _alias_entry(alias: str, model: str, body: dict[str, Any]) -> dict[str, Any]:
    data_class = str(body.get("data_policy_class") or "").strip().lower()
    if data_class not in DATA_POLICY_CLASSES:
        raise _refused(f"data_policy_class is one of: {', '.join(sorted(DATA_POLICY_CLASSES))}")
    try:
        context = int(body.get("context_limit") or 0)
        prices = [float(body.get(key) or 0) for key in ("input_per_million_usd", "output_per_million_usd")]
    except (TypeError, ValueError):
        raise _refused("context_limit and the prices are numbers") from None
    if context <= 0:
        raise _refused("context_limit is positive")
    if free := str(body.get("free_reference") or "").strip():
        cost: dict[str, Any] = {"source": "governed_free", "contract_reference": free}
    elif all(price > 0 for price in prices):
        cost = {"source": "catalog_pricing", "input_per_million_usd": prices[0], "output_per_million_usd": prices[1]}
    else:
        # The gateway admits a priced alias only with both rates above 0; refused before LiteLLM changes.
        raise _refused("the input and output prices (USD per million tokens) are required and above 0")
    # LiteLLM answers with the route's name (the model group) or the upstream id.
    return {"model_group": alias, "context_limit": context, "data_policy_class": data_class,
            "capabilities": {"tools": bool(body.get("tools"))}, "served_model_ids": [model], "cost": cost}


def _params(kind: ProviderType, model: str, credentials: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    given = {key: str(value).strip() for key, value in dict(credentials or {}).items()
             if key in kind.fields and str(value or "").strip()}
    missing = [key for key in kind.required if key not in given]
    if creating and missing:
        raise _refused(f"{', '.join(missing)} is required for this provider type")
    return {"model": f"{kind.prefix}/{model}", **given}


async def _sync(db: AsyncSession, provider: LLMProvider) -> None:
    from ..control_plane_service import build_provider_client_kwargs_async
    from ..provider.service import sync_provider_models

    await db.commit()
    await sync_provider_models(db, provider_id=provider.id,
                               build_provider_client_kwargs_async_func=build_provider_client_kwargs_async)


async def save_route(db: AsyncSession, body: dict[str, Any], *, alias: str | None = None) -> dict[str, Any]:
    provider = await _bundled_provider(db)
    creating = alias is None
    alias = str(body.get("alias") if creating else alias or "").strip().lower()
    if not _ALIAS.match(alias):
        raise _refused("alias: lower-case letters, digits, '.', '_' and '-', at most 63 characters")
    kind = PROVIDER_TYPES.get(str(body.get("provider_type") or ""))
    model = str(body.get("model") or "").strip()
    if kind is None or not model:
        raise _refused(f"provider_type is one of: {', '.join(PROVIDER_TYPES)}; model is required")
    entry = _alias_entry(alias, model, body)
    deployments = await _deployments()
    existing = deployments.get(alias)
    if creating and (existing is not None or alias in _aliases(provider)):
        raise _refused(f"a route named {alias} exists", 409)
    if not creating and existing is None:
        raise _refused(f"no route named {alias}", 404)
    params = _params(kind, model, dict(body.get("credentials") or {}), creating=creating)
    # LiteLLM reports a model's capabilities from its model_info; a model its own catalog does not know states them
    # here, as the admin declared them.
    info = {TYPE_KEY: str(body.get("provider_type")), "supports_function_calling": bool(body.get("tools"))}
    if creating:
        await _litellm("POST", "/model/new", {"model_name": alias, "litellm_params": params, "model_info": info})
    else:
        model_id = str(dict(existing.get("model_info") or {}).get("id") or "")
        await _litellm("PATCH", f"/model/{model_id}/update",
                       {"model_name": alias, "litellm_params": params, "model_info": info})
    _set_aliases(provider, {**_aliases(provider), alias: entry})
    await _sync(db, provider)
    return _route_view(alias, entry, (await _deployments()).get(alias))


async def delete_route(db: AsyncSession, alias: str) -> None:
    provider = await _bundled_provider(db)
    existing = (await _deployments()).get(alias)
    if existing is not None:
        await _litellm("POST", "/model/delete", {"id": str(dict(existing.get("model_info") or {}).get("id") or "")})
    aliases = _aliases(provider)
    aliases.pop(alias, None)
    _set_aliases(provider, aliases)
    models = await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id, LLMModel.model_id == alias))
    for row in models.scalars():
        row.is_active = False
    await db.commit()


async def ensure_route(db: AsyncSession, access: Any) -> None:
    # The environment's first-start model as a route (``control_plane/env_model_access``); a second start adds none.
    provider = await _bundled_provider(db)
    if access.alias in _aliases(provider) or access.alias in await _deployments():
        return
    from ..budget.list_prices import list_price

    # Internal, at its dated list price; a model the table does not know runs as free under a named record until an
    # admin prices it in Admin › Models, so the default works from the first start.
    price = list_price(access.model)
    pricing = ({"input_per_million_usd": price.input, "output_per_million_usd": price.output} if price else
               {"free_reference": "first start without a list price: set the price in Admin › Models"})
    await save_route(db, {"alias": access.alias, "provider_type": access.provider_type, "model": access.model,
                          "credentials": dict(access.credentials), "data_policy_class": "internal",
                          "context_limit": 200000, "tools": True, **pricing})
    # Cleared for the data class it was declared with, so the first start's default answers without an admin step.
    rows = await db.execute(
        select(LLMModel).where(LLMModel.provider_id == provider.id, LLMModel.model_id == access.alias))
    for row in rows.scalars():
        row.cleared_up_to = row.cleared_up_to or "internal"
    await db.commit()


async def test_route(db: AsyncSession, alias: str) -> dict[str, Any]:
    from ..control_plane.provider_auth import PROVIDER_CREDENTIAL
    from ..secret import get_secret_value

    provider = await _bundled_provider(db)
    if alias not in _aliases(provider):
        raise _refused(f"no route named {alias}", 404)
    # With the platform's own virtual key, straight to LiteLLM: the route and its upstream credential answer. The
    # gateway's alias admission needs a Workspace and is checked on every real call.
    key = await get_secret_value(db, secret_id=provider.api_key_secret_ref, purpose=PROVIDER_CREDENTIAL)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            response = await client.post(
                f"{bundled_url()}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                json={"model": alias, "max_tokens": 16, "messages": [{"role": "user", "content": "Reply with OK."}]})
    except httpx.HTTPError as exc:
        return {"state": "error", "error": type(exc).__name__, "reason": ""}
    if response.status_code >= 400:
        return {"state": "error", "error": f"HTTP {response.status_code}", "reason": "LiteLLM or the provider refused"}
    return {"state": "ok", "latency_ms": int((time.monotonic() - started) * 1000)}


__all__ = ["PROVIDER_TYPES", "delete_route", "ensure_route", "list_routes", "save_route", "test_route"]
