from __future__ import annotations

from tests.guards._support import Accepted, Allowed


def _sites(reason: str, wp: str, path: str, *sites: str) -> tuple[Allowed, ...]:
    return tuple(Allowed(f"{path}::{site}", reason, wp) for site in sites)


def _PROVIDER(path: str, *sites: str) -> tuple[Allowed, ...]:  # noqa: N802
    return _sites("provider/driver name outside the driver layer; M3 leaves provider names only in the "
                  "supported-type definition", "WP-M3", path, *sites)


def _ENGINE(path: str, *sites: str) -> tuple[Allowed, ...]:  # noqa: N802
    return _sites("engine name outside the engine registry; the engine driver interface replaces it", "WP-R1",
                  path, *sites)


# The supported provider types of the bundled LiteLLM: the one definition where provider names stay (V002-PLAN 3.6).
_PROVIDER_TYPES = tuple(
    Accepted(f"app/services/model_gateway/bundled_routes.py::<module>: {{'{name}': ...}}",
             "the supported provider types of the bundled LiteLLM, the one definition provider names keep")
    for name in ("anthropic", "gemini", "openai"))

ALLOWED_SPECIAL_CASES: tuple[Allowed | Accepted, ...] = (
    *_PROVIDER_TYPES,
    *_ENGINE("app/api/routes/agent_gateway/agent_gateway.py",
        "_codex_seat: decision.allowed and ENGINE_CODEX not in (await effective_engine(db, user_id=identity.user.id, workspace_id=identity.workspace_id)).allowed"),
    *_ENGINE("app/api/routes/agent_gateway/agent_gateway_presence.py",
        "_seat_refusal: codex and ENGINE_CODEX not in (await effective_engine(db, user_id=identity.user.id, workspace_id=identity.workspace_id)).allowed",
        "register_gateway_session: not isinstance(answer, str) and body.get('engine') == ENGINE_CODEX"),
    *_ENGINE("app/services/agent_gateway/review_keys.py",
        "model_family: name.startswith('claude-') or name in ('haiku', 'sonnet', 'opus')"),
    *_ENGINE("app/services/agent_gateway/seat_policy_keys.py",
        "_baseline: str(model).startswith('claude-')"),
    *_ENGINE("app/services/agent_gateway/usage_read.py",
        "_engine: engine == ENGINE_CODEX"),
    *_PROVIDER("app/services/control_plane/client_kwargs.py",
        "build_provider_client_kwargs_async: provider is not None and kwargs.get('driver') == 'litellm_gateway'",


        "build_provider_client_kwargs: runtime['driver'] == 'litellm_gateway'",




        ),
    *_sites("the bundled LiteLLM's gateway config section; the one LiteLLM client M3 keeps", "WP-M3",
            "app/services/model_gateway/bundled_litellm.py", "provider_config: {GATEWAY_CONFIG_KEY: ...}"),
    *_PROVIDER("app/services/control_plane/env_model_access.py",
        "<module>: {'anthropic': ...}",
        "<module>: {'openai': ...}",

        "env_model_access: kind == 'anthropic'",
        "env_model_access: kind == 'openai'"),
    *_PROVIDER("app/services/control_plane/runtime_temperature.py",
        "effective_temperature: driver != DRIVER_LITELLM_GATEWAY",
        "temperature_warning: driver != DRIVER_LITELLM_GATEWAY or getattr(target, 'accepts_temperature', None) is not None"),
    *_ENGINE("app/services/devices/seat_quota.py",
        "_engine_filter: engine == ENGINE_CODEX"),
    *_PROVIDER("app/services/observability/agent_metrics.py",
        "<module>: {'anthropic': ...}",
        "<module>: {'claude_code': ...}",
        "<module>: {'codex': ...}",
        "<module>: {'openai': ...}"),
    *_ENGINE("app/services/pr_review_bot/fix_command.py",
        "<module>: {'claude': ...}",
        "<module>: {'codex': ...}"),
    *_PROVIDER("app/services/provider/readiness.py",
        "_missing_gateway_contract_reason: runtime['driver'] != LITELLM_GATEWAY_DRIVER"),
    *_PROVIDER("app/services/setup_guide/model_checks.py",
        "default_step: provider.driver == GATEWAY_DRIVER and (not _admitted(provider, _target.model_id))",
        "gateway_step: provider.driver == GATEWAY_DRIVER"),
    *_PROVIDER("app/services/tts/service.py",
        "_build_tts_provider: provider.provider == 'openai'",
        "is_tts_provider_available: provider.provider == 'openai'",
        "list_tts_providers: {'openai': ...}"),
    *_ENGINE("app/services/workflow_runs/octryx/contract_phase.py",
        "_runs_codex: isinstance(metadata, dict) and metadata.get(SESSION_ENGINE_KEY) == ENGINE_CODEX"),
    *_ENGINE("app/services/workflow_runs/octryx/model_guard.py",
        "RunModels.replacement: engine == ENGINE_CODEX"),
    *_ENGINE("app/services/workflow_runs/review/seat.py",
        "<module>: {'claude_code': ...}",
        "<module>: {ENGINE_CODEX: ...}"),
    *_ENGINE("app/services/workflow_runs/review/seat_fallback.py",
        "_model_not_admitted: choice.engine != ENGINE_CLAUDE_CODE or not run.project_id"),
    *_PROVIDER("app/services/workspace_models/contract.py",
        "model_catalog: provider.is_active and provider.driver == LITELLM_GATEWAY_DRIVER"),
)
