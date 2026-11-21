"""LLM-backed security analyzer helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.out_of_turn import prompt_set_for

from ...agent.providers import get_provider
from ...models import LLMModel, LLMProvider
from ...services.content_security.model_call_scope import model_call_scope, session_call
from ...services.content_security.untrusted_fence import untrusted_section
from ...services.control_plane_service import (
    build_provider_client_kwargs_async,
    ensure_control_plane_defaults,
    get_runtime_targets,
)
from ...services.model_gateway.dispatch_admission import (
    DispatchAdmissionDeniedError,
    admit_client_kwargs_for_dispatch,
)
from ...services.system_config import get_agent_runtime_settings
from ...tools.context import ToolContext
from ..error_facts import error_facts
from ..model_gateway.litellm.project_admission import PROJECT_ADMISSION_KWARG
from ..model_gateway.litellm.runtime_admission import runtime_uses_gateway_driver
from .contract import SecurityAnalyzerFinding, _action_rank
from .helpers import (
    _capability_type,
    _command_text_and_tokens,
    _extract_json_object,
    _score_to_action,
    _score_to_risk_level,
)

_DEFAULT_LLM_RISK_TIMEOUT_SECONDS = 8
_DEFAULT_LLM_RISK_REVIEW_THRESHOLD = 40
_DEFAULT_LLM_RISK_DENY_THRESHOLD = 80

# The kwargs this analyzer has always passed. Every other driver infers endpoint,
# config and timeout from its own provider row, so widening this surface for them
# would change non-gateway construction — the gateway's own fields are added only
# when the admitted target actually is the gateway. The sampling choice (the target's
# never send, the model's catalog temperature) is passed too: only the clients that
# apply it (direct Bedrock, the gateway) read it, so a model that rejects a
# temperature is not sent one here either.
_BASE_CLIENT_KEYS = (
    "api_key",
    "region",
    "role_arn",
    "copilot_token",
    "auth_mode",
    "accepts_temperature",
    "target_temperature",
)
_GATEWAY_CLIENT_KEYS = ("driver", "endpoint_url", "config_json", PROJECT_ADMISSION_KWARG)


def _provider_client_kwargs(runtime: Mapping[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"provider_name": str(runtime.get("provider_name") or "")}
    for key in _BASE_CLIENT_KEYS:
        kwargs[key] = runtime.get(key)
    if runtime_uses_gateway_driver(dict(runtime)):
        for key in _GATEWAY_CLIENT_KEYS:
            kwargs[key] = runtime.get(key)
    return kwargs


# The JSON keys and enums the analyzer parses: fixed protocol, fills ``{answer_contract}`` of
# ``judge.security.risk``.
RISK_ANSWER_CONTRACT = (
    "Return strict JSON only with keys: score, recommended_action, risk_level, reason, signals, confidence.\n"
    "score must be an integer from 0 to 100.\n"
    "recommended_action must be one of allow, review, deny.\n"
    "risk_level must be one of low, medium, high, critical.\n"
    "signals must be a flat list of short strings.\n"
    "confidence must be a float between 0 and 1."
)



def _first_set(project_config: Any, runtime_settings: Any, key: str, default: int) -> int:
    """The Workspace's value, else the platform's, else ``default`` — a stored 0 is a value."""
    for source in (project_config, runtime_settings):
        value = source.get(key) if isinstance(source, dict) else None
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default

async def _resolve_llm_risk_runtime(
    db: AsyncSession,
    *,
    project_config: Mapping[str, Any] | None,
    runtime_settings: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    config = await ensure_control_plane_defaults(db)
    targets = await get_runtime_targets(db, config, active_only=True)
    target = targets[0] if targets else None
    provider = await db.get(LLMProvider, target.provider_id) if target else None
    client_kwargs = await build_provider_client_kwargs_async(db, provider)
    fallback_model = str(
        (target.model_id if target else "") or runtime_settings.get("agent_default_model") or ""
    ).strip()
    model = (
        str(
            (project_config or {}).get("security_review_model") or runtime_settings.get("security_review_model") or ""
        ).strip()
        or fallback_model
    )
    if not model:
        raise RuntimeError("No model is configured for llm_risk analysis")
    # The target's sampling override belongs to its own model; another security_review_model gets the catalog rule.
    target_model = target is not None and model == str(target.model_id or "").strip()
    catalog_row = (await db.execute(select(LLMModel).where(
        LLMModel.provider_id == provider.id, LLMModel.model_id == model))).scalars().first() if provider else None
    runtime = {
        **client_kwargs,
        "provider_name": client_kwargs.get("provider_name") or (provider.name if provider else "openrouter"),
        "provider_id": provider.id if provider else None,
        "model": model,
        "accepts_temperature": getattr(target, "accepts_temperature", None) if target_model else None,
        "target_temperature": getattr(catalog_row, "temperature", None),
    }
    provider_label = str(provider.display_name or provider.name) if provider else str(runtime["provider_name"])
    return runtime, provider_label


async def _run_llm_risk_model(
    tool_name: str,
    command_text: str,
    context: ToolContext,
    *,
    runtime_settings: Mapping[str, Any],
) -> dict[str, Any]:
    if context.db is None:
        raise RuntimeError("DB context is required for llm_risk analysis")
    runtime, provider_label = await _resolve_llm_risk_runtime(
        context.db,
        project_config=context.project_config,
        runtime_settings=runtime_settings,
    )
    timeout_seconds = _first_set(context.project_config, runtime_settings, "llm_security_analyzer_timeout_seconds",
                                 _DEFAULT_LLM_RISK_TIMEOUT_SECONDS)
    # The Workspace is the tool call's own resolved project config, never a
    # command argument. A gateway target the Workspace has not granted is refused
    # here, before a client exists, and the analyzer reports it as an explicit
    # admission state.
    admission = await admit_client_kwargs_for_dispatch(
        context.db,
        runtime,
        model=str(runtime.get("model") or ""),
        # The turn's Workspace, stamped into the project config server-side by
        # ``assemble_turn_project_config``. Absent means no Workspace was
        # resolved for the turn, which is a configuration gap, not an allow.
        project_ids=(context.project_config or {}).get("project_id"),
        owner="security_analyzer_llm_risk",
    )
    if not admission.allowed:
        raise DispatchAdmissionDeniedError(admission)
    admitted_runtime = admission.first_dispatchable_runtime() or {}
    client = get_provider(**_provider_client_kwargs(admitted_runtime))
    project_label = str(
        (context.project_config or {}).get("project_name")
        or (context.project_config or {}).get("project_id")
        or "unknown"
    )
    prompts = await prompt_set_for(context.db, workspace_id=(context.project_config or {}).get("project_id"))
    prompt = prompts.render(
        "judge.security.risk",
        answer_contract=RISK_ANSWER_CONTRACT,
        tool_name=tool_name,
        capability=_capability_type(context),
        project_label=project_label,
        # The command is the subject under judgement: a comment in it must not steer the verdict.
        command_text=untrusted_section("command", command_text, source="the agent whose command is judged"),
    )
    # The turn's Workspace (the one the runtime was admitted for), or a session without one.
    scope = session_call((context.project_config or {}).get("project_id"), session_id=context.session_id,
                         user_id=context.user_id)
    try:
        with model_call_scope(scope):
            response = await asyncio.wait_for(
                client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=str(runtime.get("model") or ""),
                    tools=None,
                    max_tokens=400,
                ),
                timeout=timeout_seconds,
            )
    finally:
        await client.close()
    payload = _extract_json_object(str(response.get("content") or ""))
    payload["provider_name"] = str(runtime.get("provider_name") or "")
    payload["provider_display_name"] = provider_label
    payload["model"] = str(runtime.get("model") or "")
    return payload


async def _llm_risk_analyzer(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> SecurityAnalyzerFinding:
    if context.db is None:
        return SecurityAnalyzerFinding(
            analyzer="llm_risk",
            action="allow",
            risk_level="low",
            reason="No DB context available for llm_risk analysis.",
            details={},
        )

    runtime_settings = await get_agent_runtime_settings(context.db)
    review_threshold = _first_set(context.project_config, runtime_settings, "llm_security_analyzer_review_threshold",
                                  _DEFAULT_LLM_RISK_REVIEW_THRESHOLD)
    deny_threshold = _first_set(context.project_config, runtime_settings, "llm_security_analyzer_deny_threshold",
                                _DEFAULT_LLM_RISK_DENY_THRESHOLD)
    if deny_threshold < review_threshold:
        deny_threshold = review_threshold
    command_text, _ = _command_text_and_tokens(command)
    try:
        payload = await _run_llm_risk_model(
            tool_name,
            command_text,
            context,
            runtime_settings=runtime_settings,
        )
    except DispatchAdmissionDeniedError as denied:
        # Distinct from a provider failure: no request was made and the Workspace
        # policy state is reported instead of a generic error string.
        return SecurityAnalyzerFinding(
            analyzer="llm_risk",
            action="review",
            risk_level="medium",
            reason=(
                "LLM-backed risk analysis is not admitted for this Workspace while llm_risk is "
                "enabled, so manual review is required."
            ),
            details=denied.to_result(),
        )
    except Exception as exc:
        return SecurityAnalyzerFinding(
            analyzer="llm_risk",
            action="review",
            risk_level="medium",
            reason="LLM-backed risk analysis failed while llm_risk is enabled, so manual review is required.",
            details=error_facts("llm_risk_analysis_failed", exc),
        )

    try:
        score = int(float(payload.get("score")))
    except (TypeError, ValueError):
        score = review_threshold
    score = max(0, min(score, 100))
    threshold_action = _score_to_action(
        score=score,
        review_threshold=review_threshold,
        deny_threshold=deny_threshold,
    )
    suggested_action = str(payload.get("recommended_action") or "").strip().lower()
    suggested_action = suggested_action if suggested_action in {"allow", "review", "deny"} else "allow"
    final_action = threshold_action
    if _action_rank(suggested_action) > _action_rank(final_action):
        final_action = suggested_action
    risk_level = str(payload.get("risk_level") or "").strip().lower()
    if risk_level not in {"low", "medium", "high", "critical"}:
        risk_level = _score_to_risk_level(score)
    reason = str(payload.get("reason") or "").strip() or "LLM risk analyzer provided no reason."
    signals = payload.get("signals")
    if not isinstance(signals, list):
        signals = []
    return SecurityAnalyzerFinding(
        analyzer="llm_risk",
        action=final_action,
        risk_level=risk_level,
        reason=reason,
        details={
            "score": score,
            "threshold_action": threshold_action,
            "review_threshold": review_threshold,
            "deny_threshold": deny_threshold,
            "recommended_action": suggested_action,
            "confidence": payload.get("confidence"),
            "signals": [str(item).strip() for item in signals if str(item).strip()],
            "provider_name": payload.get("provider_name"),
            "provider_display_name": payload.get("provider_display_name"),
            "model": payload.get("model"),
        },
    )


__all__ = [
    "_llm_risk_analyzer",
    "_resolve_llm_risk_runtime",
    "_run_llm_risk_model",
]
