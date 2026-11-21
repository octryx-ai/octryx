"""Runtime governance: chain behavior, readiness, and the governed fallback mode.

A refusal is never silent and never free: a denied target leaves a zero-dispatch
attempt, a served contract violation stops the chain instead of buying a second
billable answer, a pre-dispatch configuration gap still falls back, and the
cross-runtime fallback mode is writable only through the validated admin
surface — schema, route, and service writer.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.core.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIED_STATUS
from app.agent.core.runtime.runtime_errors import (
    NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES,
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_CONTRACT_VIOLATION,
    RUNTIME_ERROR_FALLBACK_VIOLATION,
)
from app.agent.core.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
from app.agent.engine.runtime._engine_runtime_admission import CHAIN_HALT_ERROR_CLASS
from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
from app.services.model_gateway.litellm import (
    LiteLLMGatewayError,
    ProjectModelAdmission,
    apply_model_policy_to_runtimes,
)
from app.services.model_gateway.litellm.client import ENDPOINT_DENIAL_REDIRECTED
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
)
from tests.model_gateway.conftest import (
    ALIAS,
    MESSAGES,
    PROJECT_ID,
    RecordingRuntimeFactory,
    backup_runtime,
    gateway_runtime,
    granted_project_config,
    workspace_classification,
)


async def _run_chain(
    runtimes: list[dict[str, Any]],
    factory: RecordingRuntimeFactory,
    *,
    fallback_mode: str = RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
) -> tuple[dict, dict, list[dict[str, Any]]]:
    return await _chat_with_runtime_fallback(
        runtimes,
        messages=MESSAGES,
        tools=None,
        get_provider_func=factory,
        retry_policy={"max_retries": 0, "pause_seconds": 0, "fallback_mode": fallback_mode},
    )


async def test_fallback_violation_stops_the_runtime_chain() -> None:
    factory = RecordingRuntimeFactory(
        failures={"litellm": LiteLLMGatewayError(GATEWAY_STATE_FALLBACK_VIOLATION)}
    )

    with pytest.raises(RuntimeError) as excinfo:
        await _run_chain([gateway_runtime(), backup_runtime()], factory)

    assert factory.dispatched == ["litellm"]
    attempts = excinfo.value.runtime_attempts
    assert any(item.get("error_class") == RUNTIME_ERROR_FALLBACK_VIOLATION for item in attempts)
    halt = [item for item in attempts if item.get("error_class") == CHAIN_HALT_ERROR_CLASS]
    assert halt and halt[0]["skipped_runtime_count"] == 1


async def test_a_cost_contract_violation_never_buys_a_second_call() -> None:
    """A deterministic response-contract violation is terminal, not a fallback."""

    factory = RecordingRuntimeFactory(
        failures={
            "litellm": LiteLLMGatewayError(
                GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
                denial_reason="gateway_cost_not_positive",
            )
        }
    )

    with pytest.raises(RuntimeError) as excinfo:
        await _run_chain([gateway_runtime(), backup_runtime()], factory)

    assert factory.dispatched == ["litellm"]
    assert RUNTIME_ERROR_CONTRACT_VIOLATION in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES
    assert any(
        item.get("error_class") == RUNTIME_ERROR_CONTRACT_VIOLATION for item in excinfo.value.runtime_attempts
    )


async def test_a_pre_dispatch_configuration_gap_stays_fallbackable() -> None:
    """Configuration gaps, including a redirected endpoint, are not terminal.

    Nothing was served, so the chain may still use its other targets: a
    misconfigured gateway must not hard-fail a turn that has a working runtime.
    """

    for denial_reason in ("probe_contract_missing", ENDPOINT_DENIAL_REDIRECTED):
        factory = RecordingRuntimeFactory(
            failures={
                "litellm": LiteLLMGatewayError(
                    GATEWAY_STATE_CONFIGURATION_INVALID,
                    denial_reason=denial_reason,
                )
            }
        )

        response, _runtime, _attempts = await _run_chain([gateway_runtime(), backup_runtime()], factory)

        assert factory.dispatched == ["litellm", "backup"]
        assert response["content"] == "backup answer"


async def test_denied_alias_never_builds_a_provider_client() -> None:
    factory = RecordingRuntimeFactory(forbidden=("litellm",))
    runtimes = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config={},
        project_id=PROJECT_ID,
    )

    response, used_runtime, attempts = await _run_chain(runtimes, factory)

    # The gateway target was never constructed; the admitted target served.
    assert factory.constructed == ["backup"]
    assert response["content"] == "backup answer"
    assert used_runtime["target_id"] == "t2"
    denied = [item for item in attempts if item.get("status") == RUNTIME_ADMISSION_DENIED_STATUS]
    assert denied and denied[0]["dispatched"] is False
    assert denied[0]["error_class"] == RUNTIME_ERROR_ALIAS_DENIED
    assert denied[0]["admission_evidence"]["alias"] == ALIAS
    assert denied[0]["admission_evidence"]["project_admission_source"] == "prepare_agent_run"


async def test_a_fully_denied_chain_dispatches_nothing_and_fails_explicitly() -> None:
    factory = RecordingRuntimeFactory(forbidden=("litellm",))
    runtimes = apply_model_policy_to_runtimes([gateway_runtime()], project_config={}, project_id=PROJECT_ID)

    with pytest.raises(RuntimeError) as excinfo:
        await _run_chain(runtimes, factory)

    assert factory.constructed == []
    attempts = excinfo.value.runtime_attempts
    assert all(item.get("dispatched") is False for item in attempts)
    assert all(item.get("status") == RUNTIME_ADMISSION_DENIED_STATUS for item in attempts)


async def test_main_chat_dispatch_carries_the_project_admission_into_the_factory() -> None:
    """Main chat path: runtime boundary grant -> factory kwarg -> driver."""

    factory = RecordingRuntimeFactory()
    runtimes = apply_model_policy_to_runtimes(
        [gateway_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification(),
    )

    response, _runtime, _attempts = await _run_chain(runtimes, factory)

    assert response["content"] == "litellm answer"
    assert len(factory.seen_admissions) == 1
    assert isinstance(factory.seen_admissions[0], ProjectModelAdmission)
    assert factory.seen_admissions[0].verified is True
