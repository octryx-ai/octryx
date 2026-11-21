"""Helpers for local Ollama/Gemma bootstrap and health management."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.providers import infer_provider_runtime
from ...time_utils import utc_now
from ..control_plane_service import get_or_create_control_plane_config, get_runtime_targets, upsert_runtime_target
from ..error_facts import error_text
from ..local_runtime_orchestrator import ensure_local_runtime_started, ensure_provider_local_runtime_ready
from ..provider_runtime_config import apply_provider_runtime_defaults
from .bootstrap_ensure import ensure_local_bootstrap as _ensure_local_bootstrap_impl
from .impl import (
    get_local_bootstrap_status as _get_local_bootstrap_status_impl,
)
from .impl import (
    pull_provider_model as _pull_provider_model_impl,
)
from .impl import (
    refresh_provider_health as _refresh_provider_health_impl,
)

HOST_LOCAL_BOOTSTRAP_ENDPOINT = "http://localhost:11434"
DOCKER_LOCAL_BOOTSTRAP_ENDPOINT = "http://ollama:11434"
DEFAULT_LOCAL_BOOTSTRAP_MODEL = "gemma4"
DEFAULT_LOCAL_BOOTSTRAP_MODEL_VARIANT = "gemma4:e4b"
DEFAULT_LOCAL_BOOTSTRAP_DISPLAY_NAME = "Local Gemma 4 Anchor"
DEFAULT_LOCAL_BOOTSTRAP_PROFILE = "bootstrap"


def default_ollama_base_url() -> str:
    env_override = str(os.getenv("OLLAMA_BASE_URL") or "").strip().rstrip("/")
    if env_override:
        return env_override
    return DOCKER_LOCAL_BOOTSTRAP_ENDPOINT if os.path.exists("/.dockerenv") else HOST_LOCAL_BOOTSTRAP_ENDPOINT


def normalize_ollama_base_url(base_url: str | None) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    return normalized or default_ollama_base_url()


def _ollama_base_url_candidates(base_url: str | None) -> list[str]:
    requested = str(base_url or "").strip().rstrip("/")
    candidates = [
        requested,
        default_ollama_base_url(),
        HOST_LOCAL_BOOTSTRAP_ENDPOINT,
        DOCKER_LOCAL_BOOTSTRAP_ENDPOINT,
    ]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _trim_error(error: str) -> str:
    text = str(error or "").strip()
    return f"{text[:497]}..." if len(text) > 500 else text


def _ollama_error_text(code: str, exc: BaseException) -> str:
    """Fixed facts for an Ollama call failure: code, class name and, when known, the HTTP status."""
    text = error_text(code, exc)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        text = f"{text} http_status={int(exc.response.status_code)}"
    return text


def _serialize_probe_model(item: dict[str, Any]) -> dict[str, Any]:
    model_id = str(item.get("name") or item.get("model") or "").strip()
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    context_length = details.get("context_length") or item.get("context_length")
    return {
        "id": model_id,
        "context_length": int(context_length) if isinstance(context_length, int) else None,
    }


def _preferred_ollama_model_variants(model_id: str) -> list[str]:
    normalized = str(model_id or "").strip()
    if not normalized:
        return []
    if normalized == "gemma4":
        return [DEFAULT_LOCAL_BOOTSTRAP_MODEL_VARIANT, "gemma4:e2b"]
    return [normalized]


def resolve_ollama_model_id(model_id: str | None, available_model_ids: list[str] | None) -> str:
    requested = str(model_id or "").strip() or DEFAULT_LOCAL_BOOTSTRAP_MODEL
    available = [str(item).strip() for item in (available_model_ids or []) if str(item).strip()]
    if requested in available:
        return requested
    for preferred in _preferred_ollama_model_variants(requested):
        if preferred in available:
            return preferred
    if requested == "gemma4":
        gemma_variants = [item for item in available if item == "gemma4" or item.startswith("gemma4:")]
        for preferred in [DEFAULT_LOCAL_BOOTSTRAP_MODEL_VARIANT, "gemma4:e2b"]:
            if preferred in gemma_variants:
                return preferred
        if gemma_variants:
            return sorted(gemma_variants)[0]
    return ""


def canonicalize_ollama_pull_model(model_id: str | None) -> str:
    requested = str(model_id or "").strip() or DEFAULT_LOCAL_BOOTSTRAP_MODEL
    if requested == "gemma4":
        return DEFAULT_LOCAL_BOOTSTRAP_MODEL_VARIANT
    return requested


async def probe_ollama_endpoint(
    base_url: str,
    *,
    timeout_seconds: float = 20.0,
    async_client_cls=httpx.AsyncClient,
) -> dict[str, Any]:
    attempted = _ollama_base_url_candidates(base_url)
    errors: list[str] = []
    for candidate in attempted:
        try:
            async with async_client_cls(base_url=candidate, timeout=timeout_seconds) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                data = response.json()
            models = [
                serialized
                for item in data.get("models", []) or []
                if (serialized := _serialize_probe_model(item)).get("id")
            ]
            return {
                "ok": True,
                "status": "ok",
                "base_url": candidate,
                "requested_base_url": normalize_ollama_base_url(base_url),
                "attempted_base_urls": attempted,
                "models": models,
                "model_ids": [model["id"] for model in models],
                "error": "",
            }
        except Exception as exc:
            errors.append(f"{candidate}: {_ollama_error_text('ollama_probe_failed', exc)}")
    return {
        "ok": False,
        "status": "error",
        "base_url": attempted[0] if attempted else normalize_ollama_base_url(base_url),
        "requested_base_url": normalize_ollama_base_url(base_url),
        "attempted_base_urls": attempted,
        "models": [],
        "model_ids": [],
        "error": _trim_error(" | ".join(errors)),
    }


async def pull_ollama_model(
    base_url: str,
    *,
    model_id: str,
    timeout_seconds: float = 1800.0,
    async_client_cls=httpx.AsyncClient,
) -> dict[str, Any]:
    normalized = normalize_ollama_base_url(base_url)
    requested_model = canonicalize_ollama_pull_model(model_id)
    if not requested_model:
        raise HTTPException(status_code=400, detail="model_id is required")
    try:
        async with async_client_cls(base_url=normalized, timeout=timeout_seconds) as client:
            response = await client.post("/api/pull", json={"model": requested_model, "stream": False})
            response.raise_for_status()
            data = response.json() if response.content else {}
        return {
            "ok": True,
            "status": "ok",
            "base_url": normalized,
            "model_id": requested_model,
            "details": data if isinstance(data, dict) else {},
        }
    except Exception as exc:
        # Neither the Ollama response body nor the client error text is echoed.
        raise HTTPException(
            status_code=400,
            detail=f"Ollama pull failed. {_ollama_error_text('ollama_pull_failed', exc)}",
        ) from exc


async def get_local_bootstrap_status(db: AsyncSession) -> dict[str, Any]:
    return await _get_local_bootstrap_status_impl(
        db,
        default_local_bootstrap_model=DEFAULT_LOCAL_BOOTSTRAP_MODEL,
        default_local_bootstrap_display_name=DEFAULT_LOCAL_BOOTSTRAP_DISPLAY_NAME,
        default_local_bootstrap_profile=DEFAULT_LOCAL_BOOTSTRAP_PROFILE,
        default_ollama_base_url_func=default_ollama_base_url,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
    )


async def refresh_provider_health(
    db: AsyncSession,
    *,
    provider_id: str,
) -> dict[str, Any]:
    return await _refresh_provider_health_impl(
        db,
        provider_id=provider_id,
        infer_provider_runtime_func=infer_provider_runtime,
        ensure_provider_local_runtime_ready_func=ensure_provider_local_runtime_ready,
        probe_ollama_endpoint_func=probe_ollama_endpoint,
        default_ollama_base_url_func=default_ollama_base_url,
        apply_provider_runtime_defaults_func=apply_provider_runtime_defaults,
        utc_now_func=utc_now,
    )


async def pull_provider_model(
    db: AsyncSession,
    *,
    provider_id: str,
    model_id: str,
) -> dict[str, Any]:
    return await _pull_provider_model_impl(
        db,
        provider_id=provider_id,
        model_id=model_id,
        infer_provider_runtime_func=infer_provider_runtime,
        pull_ollama_model_func=pull_ollama_model,
        default_ollama_base_url_func=default_ollama_base_url,
        refresh_provider_health_func=refresh_provider_health,
    )


async def ensure_local_bootstrap(
    db: AsyncSession,
    *,
    endpoint_url: str | None = None,
    model_id: str = DEFAULT_LOCAL_BOOTSTRAP_MODEL,
    display_name: str = DEFAULT_LOCAL_BOOTSTRAP_DISPLAY_NAME,
    pull_model: bool = True,
    make_primary: bool = True,
) -> dict[str, Any]:
    return await _ensure_local_bootstrap_impl(
        db,
        endpoint_url=endpoint_url,
        model_id=model_id,
        display_name=display_name,
        pull_model=pull_model,
        make_primary=make_primary,
        default_local_bootstrap_model=DEFAULT_LOCAL_BOOTSTRAP_MODEL,
        default_local_bootstrap_display_name=DEFAULT_LOCAL_BOOTSTRAP_DISPLAY_NAME,
        default_local_bootstrap_profile=DEFAULT_LOCAL_BOOTSTRAP_PROFILE,
        normalize_ollama_base_url_func=normalize_ollama_base_url,
        ensure_local_runtime_started_func=ensure_local_runtime_started,
        probe_ollama_endpoint_func=probe_ollama_endpoint,
        resolve_ollama_model_id_func=resolve_ollama_model_id,
        pull_ollama_model_func=pull_ollama_model,
        apply_provider_runtime_defaults_func=apply_provider_runtime_defaults,
        upsert_runtime_target_func=upsert_runtime_target,
        get_or_create_control_plane_config_func=get_or_create_control_plane_config,
        get_runtime_targets_func=get_runtime_targets,
        utc_now_func=utc_now,
        default_ollama_base_url_func=default_ollama_base_url,
    )
