"""Shared model catalog sync contract for provider admin/public surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.agent.runtime.runtime_errors import ProviderRuntimeError

try:  # httpx is part of the backend runtime; keep import defensive for narrow test contexts.
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

MODEL_SYNC_STATE_SUCCESS = "success"
MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE = "provider_unavailable"
MODEL_SYNC_STATE_AUTH_DENIED = "auth_denied"
MODEL_SYNC_STATE_VALIDATION_FAILED = "validation_failed"
MODEL_SYNC_STATE_STALE_CACHE = "stale_cache"
MODEL_SYNC_STATE_NO_MODELS = "no_models"

_MODEL_SYNC_ERROR_HTTP_STATUS = {
    MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE: 503,
    MODEL_SYNC_STATE_AUTH_DENIED: 401,
    MODEL_SYNC_STATE_VALIDATION_FAILED: 422,
    MODEL_SYNC_STATE_STALE_CACHE: 503,
}
@dataclass(frozen=True, slots=True)
class ModelCatalogSyncError(RuntimeError):
    sync_state: str
    safe_message: str
    error_class: str = "ModelCatalogSyncError"

    def __str__(self) -> str:
        return self.safe_message


def normalize_model_catalog_payload(raw_models: Any) -> tuple[list[dict[str, Any]], int]:
    if raw_models is None:
        raise ModelCatalogSyncError(
            MODEL_SYNC_STATE_VALIDATION_FAILED,
            "Provider model catalog returned an empty response instead of a list.",
            error_class="EmptyModelCatalogPayload",
        )
    if not isinstance(raw_models, list):
        raise ModelCatalogSyncError(
            MODEL_SYNC_STATE_VALIDATION_FAILED,
            "Provider model catalog returned a non-list response.",
            error_class=type(raw_models).__name__,
        )

    models: list[dict[str, Any]] = []
    ignored = 0
    for item in raw_models:
        if not isinstance(item, dict):
            ignored += 1
            continue
        model_id = str(item.get("id") or item.get("model_id") or "").strip()
        if not model_id:
            ignored += 1
            continue
        models.append({**item, "id": model_id, "model_id": model_id})
    return models, ignored


def model_sync_success_payload(
    *,
    models_added: int,
    models_seen: int,
    models_ignored: int,
    total_models: int,
    active_models: int,
) -> dict[str, Any]:
    return {
        "status": "synced",
        "sync_state": MODEL_SYNC_STATE_SUCCESS,
        "models_added": models_added,
        "models_seen": models_seen,
        "models_ignored": models_ignored,
        "total_models": total_models,
        "active_models": active_models,
        "cache_state": "fresh",
        "message": "Provider model catalog synchronized successfully.",
    }


def model_sync_no_models_payload(
    *,
    total_models: int,
    active_models: int,
    provider_supports_model_sync: bool,
) -> dict[str, Any]:
    reason = "provider_returned_no_models" if provider_supports_model_sync else "provider_model_sync_unsupported"
    return {
        "status": MODEL_SYNC_STATE_NO_MODELS,
        "sync_state": MODEL_SYNC_STATE_NO_MODELS,
        "models_added": 0,
        "models_seen": 0,
        "models_ignored": 0,
        "total_models": total_models,
        "active_models": active_models,
        "cache_state": "unchanged" if total_models else "empty",
        "reason": reason,
        "message": "No provider model catalog entries were synchronized.",
    }


def model_sync_failure_payload(
    exc: Exception,
    *,
    total_models: int,
    active_models: int,
) -> dict[str, Any]:
    failure_state = classify_model_sync_exception(exc)
    sync_state = MODEL_SYNC_STATE_STALE_CACHE if total_models else failure_state
    return {
        "status": sync_state,
        "sync_state": sync_state,
        "failure_state": failure_state,
        "models_added": 0,
        "models_seen": 0,
        "models_ignored": 0,
        "total_models": total_models,
        "active_models": active_models,
        "cache_state": MODEL_SYNC_STATE_STALE_CACHE if total_models else "empty",
        "error_class": _safe_error_class(exc),
        "message": _safe_failure_message(sync_state=sync_state, failure_state=failure_state),
    }


def model_sync_http_status(payload: dict[str, Any]) -> int:
    sync_state = str(payload.get("failure_state") or payload.get("sync_state") or "").strip()
    return _MODEL_SYNC_ERROR_HTTP_STATUS.get(sync_state, 503)


def raise_model_sync_http_error(payload: dict[str, Any]) -> None:
    raise HTTPException(status_code=model_sync_http_status(payload), detail=payload)


def apply_model_sync_provider_metadata(provider: Any, payload: dict[str, Any], *, checked_at: datetime) -> None:
    capabilities = dict(provider.capabilities_json) if isinstance(provider.capabilities_json, dict) else {}
    sync_state = str(payload.get("sync_state") or "").strip()
    model_catalog_sync = {
        "sync_state": sync_state,
        "status": payload.get("status"),
        "failure_state": payload.get("failure_state"),
        "cache_state": payload.get("cache_state"),
        "reason": payload.get("reason"),
        "models_seen": int(payload.get("models_seen") or 0),
        "models_ignored": int(payload.get("models_ignored") or 0),
        "models_added": int(payload.get("models_added") or 0),
        "total_models": int(payload.get("total_models") or 0),
        "active_models": int(payload.get("active_models") or 0),
        "checked_at": checked_at.isoformat(),
    }
    capabilities["model_catalog_sync"] = {
        key: value for key, value in model_catalog_sync.items() if value not in (None, "")
    }
    provider.capabilities_json = capabilities
    provider.last_health_check_at = checked_at
    if sync_state == MODEL_SYNC_STATE_SUCCESS:
        provider.health_status = "ok"
        provider.last_health_error = ""
    elif sync_state == MODEL_SYNC_STATE_NO_MODELS:
        provider.health_status = MODEL_SYNC_STATE_NO_MODELS
        provider.last_health_error = ""
    else:
        provider.health_status = sync_state or "model_sync_failed"
        provider.last_health_error = str(payload.get("message") or "Provider model catalog sync failed.")


def classify_model_sync_exception(exc: Exception) -> str:
    if isinstance(exc, ModelCatalogSyncError):
        return exc.sync_state
    status_code = None
    if isinstance(exc, HTTPException | ProviderRuntimeError):
        status_code = exc.status_code
    if status_code is not None:
        return _state_for_status(status_code)
    if isinstance(exc, PermissionError):
        return MODEL_SYNC_STATE_AUTH_DENIED
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return MODEL_SYNC_STATE_VALIDATION_FAILED
    if isinstance(exc, TimeoutError):
        return MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE
    if httpx is not None:
        if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
            return MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE
        if isinstance(exc, httpx.HTTPStatusError):
            return _state_for_status(exc.response.status_code)
    return MODEL_SYNC_STATE_VALIDATION_FAILED


def _state_for_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return MODEL_SYNC_STATE_AUTH_DENIED
    if status_code in {400, 404, 409, 422}:
        return MODEL_SYNC_STATE_VALIDATION_FAILED
    return MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE


def _safe_error_class(exc: Exception) -> str:
    if isinstance(exc, ModelCatalogSyncError) and exc.error_class:
        return exc.error_class
    return type(exc).__name__


def _safe_failure_message(*, sync_state: str, failure_state: str) -> str:
    if sync_state == MODEL_SYNC_STATE_STALE_CACHE:
        return "Provider model catalog sync failed; existing model cache was retained."
    if failure_state == MODEL_SYNC_STATE_AUTH_DENIED:
        return "Provider denied model catalog access. Check provider credentials and scopes."
    if failure_state == MODEL_SYNC_STATE_PROVIDER_UNAVAILABLE:
        return "Provider model catalog is currently unavailable."
    return "Provider model catalog response could not be validated."
