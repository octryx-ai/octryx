"""Deterministic runtime selection policy for control-plane targets."""

from __future__ import annotations

from typing import Any

from ...models import ControlPlaneRuntimeTarget, LLMProvider
from ...models.runtime.llm_provider import LLMModel
from ..provider import resolve_provider_readiness

SELECTION_POLICY_VERSION = "control_plane_runtime_selection_v1"

_ENVIRONMENT_FALLBACK_READINESS = {
    "status": "unknown",
    "reason": "environment_fallback",
    "runtime_attempt_allowed": True,
    "provider_family": None,
    "driver": None,
    "runtime_kind": None,
}


def build_runtime_selection_payload(
    *,
    client_kwargs: dict[str, Any],
    provider: LLMProvider | None,
    target: ControlPlaneRuntimeTarget | None,
    model: LLMModel | None,
    model_id: str,
    priority: int,
    use_case_tags: list[str] | None,
    max_tokens_per_request: int | None,
    request_timeout_seconds: float | None,
    requires_tools: bool = False,
    requires_vision: bool = False,
    client_configuration_available: bool = True,
) -> dict[str, Any]:
    supports_tools = _model_flag(model, "supports_tools")
    supports_vision = _model_flag(model, "supports_vision")
    pricing_input = _model_number(model, "pricing_input")
    pricing_output = _model_number(model, "pricing_output")
    readiness = resolve_provider_readiness(provider)
    decision = build_runtime_selection_decision(
        provider=provider, target=target, model=model, model_id=model_id, priority=priority,
        supports_tools=supports_tools, supports_vision=supports_vision,
        pricing_input=pricing_input, pricing_output=pricing_output,
        max_tokens_per_request=max_tokens_per_request, request_timeout_seconds=request_timeout_seconds,
        requires_tools=requires_tools, requires_vision=requires_vision,
        client_configuration_available=client_configuration_available, readiness=readiness,
    )
    return {
        **client_kwargs,
        "provider_id": provider.id if provider is not None else None,
        "target_id": target.id if target is not None else None,
        "priority": priority,
        "model": model_id,
        "use_case_tags": list(use_case_tags or []),
        "accepts_temperature": getattr(target, "accepts_temperature", None),
        # The temperature lives on the Model catalog row (``LLMModel.temperature``).
        "target_temperature": getattr(model, "temperature", None),
        "supports_tools": supports_tools,
        "supports_vision": supports_vision,
        "pricing_input": pricing_input,
        "pricing_output": pricing_output,
        "max_tokens_per_request": max_tokens_per_request,
        "request_timeout_seconds": request_timeout_seconds,
        "readiness_status": readiness["status"],
        "readiness_reason": readiness["reason"],
        "readiness": readiness,
        "selection_policy": SELECTION_POLICY_VERSION,
        "selection_status": decision["status"],
        "selection_reason": decision["reason"],
        "selection_decision": decision,
    }


def build_environment_fallback_selection_payload(
    *,
    client_kwargs: dict[str, Any],
    model_id: str,
) -> dict[str, Any]:
    decision = {
        "policy": SELECTION_POLICY_VERSION,
        "status": "selected",
        "reason": "environment_fallback",
        "skipped_reasons": [],
        "inputs": {
            "priority": 1,
            "provider_active": None,
            "model_active": None,
            "readiness": _ENVIRONMENT_FALLBACK_READINESS,
            "supports_tools": None,
            "supports_vision": None,
            "requires_tools": False,
            "requires_vision": False,
            "cost": {
                "pricing_input": None,
                "pricing_output": None,
                "pricing_state": "not_configured",
                "budget_state": "not_configured",
            },
            "limits": {
                "max_tokens_per_request": None,
                "request_timeout_seconds": None,
            },
        },
    }
    return {
        **client_kwargs,
        "provider_id": None,
        "target_id": None,
        "priority": 1,
        "model": model_id,
        "max_tokens_per_request": None,
        "request_timeout_seconds": None,
        "readiness_status": _ENVIRONMENT_FALLBACK_READINESS["status"],
        "readiness_reason": _ENVIRONMENT_FALLBACK_READINESS["reason"],
        "readiness": dict(_ENVIRONMENT_FALLBACK_READINESS),
        "selection_policy": SELECTION_POLICY_VERSION,
        "selection_status": "selected",
        "selection_reason": "environment_fallback",
        "selection_decision": decision,
    }


def build_runtime_selection_decision(
    *,
    provider: LLMProvider | None,
    target: ControlPlaneRuntimeTarget | None,
    model: LLMModel | None,
    model_id: str,
    priority: int,
    supports_tools: bool | None,
    supports_vision: bool | None,
    pricing_input: float | None,
    pricing_output: float | None,
    max_tokens_per_request: int | None,
    request_timeout_seconds: float | None,
    requires_tools: bool,
    requires_vision: bool,
    client_configuration_available: bool,
    readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readiness = readiness or resolve_provider_readiness(provider)
    skipped_reasons = _selection_skip_reasons(
        provider=provider, target=target, model=model,
        supports_tools=supports_tools, supports_vision=supports_vision,
        requires_tools=requires_tools, requires_vision=requires_vision,
        client_configuration_available=client_configuration_available, readiness=readiness,
    )
    status = "skipped" if skipped_reasons else "selected"
    return {
        "policy": SELECTION_POLICY_VERSION,
        "status": status,
        "reason": skipped_reasons[0] if skipped_reasons else "selected_by_priority",
        "skipped_reasons": skipped_reasons,
        "inputs": {
            "provider_id": provider.id if provider is not None else None,
            "target_id": target.id if target is not None else None,
            "model": model_id,
            "priority": priority,
            "provider_active": bool(provider.is_active) if provider is not None else None,
            "target_active": bool(target.is_active) if target is not None else None,
            "model_active": bool(model.is_active) if model is not None else None,
            "readiness": readiness,
            "supports_tools": supports_tools,
            "supports_vision": supports_vision,
            "requires_tools": requires_tools,
            "requires_vision": requires_vision,
            "cost": {
                "pricing_input": pricing_input,
                "pricing_output": pricing_output,
                "pricing_state": "configured" if pricing_input is not None or pricing_output is not None else "missing",
                "budget_state": "not_configured",
            },
            "limits": {
                "max_tokens_per_request": max_tokens_per_request,
                "request_timeout_seconds": request_timeout_seconds,
            },
        },
    }


def runtime_selection_is_selected(payload: dict[str, Any]) -> bool:
    return payload.get("selection_status") == "selected"


def _selection_skip_reasons(
    *,
    provider: LLMProvider | None,
    target: ControlPlaneRuntimeTarget | None,
    model: LLMModel | None,
    supports_tools: bool | None,
    supports_vision: bool | None,
    requires_tools: bool,
    requires_vision: bool,
    client_configuration_available: bool,
    readiness: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if provider is None:
        reasons.append("provider_missing")
    elif not provider.is_active:
        reasons.append("provider_inactive")
    if target is None:
        reasons.append("target_missing")
    elif not target.is_active:
        reasons.append("target_inactive")
    if model is not None and not model.is_active:
        reasons.append("model_inactive")
    if requires_tools and supports_tools is not True:
        reasons.append("tools_not_supported" if supports_tools is False else "tool_support_unknown")
    if requires_vision and supports_vision is not True:
        reasons.append("vision_not_supported" if supports_vision is False else "vision_support_unknown")
    if readiness.get("runtime_attempt_allowed") is False:
        reason = str(readiness.get("reason") or "provider_not_ready").strip() or "provider_not_ready"
        if reason not in reasons:
            reasons.append(reason)
    if not client_configuration_available:
        reasons.append("client_configuration_unavailable")
    return reasons


def _model_flag(model: LLMModel | None, attr: str) -> bool | None:
    if model is None:
        return None
    value = getattr(model, attr)
    return None if value is None else bool(value)


def _model_number(model: LLMModel | None, attr: str) -> float | None:
    if model is None:
        return None
    value = getattr(model, attr)
    return float(value) if value is not None else None


__all__ = [
    "SELECTION_POLICY_VERSION",
    "build_environment_fallback_selection_payload",
    "build_runtime_selection_decision",
    "build_runtime_selection_payload",
    "runtime_selection_is_selected",
]
