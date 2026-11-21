"""Project admission at every dispatch boundary: an unverifiable project denies every gateway target, each dispatch path carries the verified admission, and the client keeps the virtual key and its transport boundary closed."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.agent.core.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIAL_KEY
from app.agent.core.runtime.runtime_errors import RUNTIME_ERROR_ALIAS_DENIED, classify_runtime_error
from app.agent.providers import get_provider
from app.agent.providers.litellm_gateway import LiteLLMGatewayClient
from app.services.control_plane_service import build_provider_client_kwargs
from app.services.model_gateway.litellm import (
    PROJECT_ADMISSION_KWARG,
    UNVERIFIED_PROJECT_ADMISSION,
    LiteLLMGatewayError,
    ProjectModelAdmission,
    apply_model_policy_to_runtimes,
)
from app.services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_ALIAS_DENIED
from tests.model_gateway.conftest import (
    ALIAS,
    BASE_URL,
    MESSAGES,
    PROJECT_ID,
    VIRTUAL_KEY,
    backup_runtime,
    gateway_config,
    gateway_provider,
    gateway_runtime,
    granted_project_config,
    verified_admission,
    workspace_classification,
)

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def test_unverifiable_project_context_denies_every_gateway_target() -> None:
    # No server-owned project id: the policy cannot be evaluated at all.
    without_project = apply_model_policy_to_runtimes(
        [gateway_runtime()],
        project_config=granted_project_config(),
        project_id=None,
    )

    denial = without_project[0][RUNTIME_ADMISSION_DENIAL_KEY]
    assert denial["reason"] == "project_policy_context_unverifiable"
    assert denial["evidence"]["project_admission_source"] == "unverified_project_context"
    assert PROJECT_ADMISSION_KWARG not in without_project[0]


def test_admitted_gateway_runtime_carries_the_verified_admission() -> None:
    runtimes = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification(),
    )

    admission = runtimes[0][PROJECT_ADMISSION_KWARG]
    assert isinstance(admission, ProjectModelAdmission)
    assert admission.verified is True and admission.project_id == PROJECT_ID
    assert admission.decide(ALIAS).allowed is True
    # Non-gateway runtimes keep their exact previous shape.
    assert PROJECT_ADMISSION_KWARG not in runtimes[1]


def test_gateway_dispatch_boundaries_require_a_project_admission(gateway) -> None:
    """Neither the driver nor the factory serves a caller without a project."""

    with pytest.raises(LiteLLMGatewayError) as driver_denial:
        LiteLLMGatewayClient(
            endpoint_url=BASE_URL,
            api_key=VIRTUAL_KEY,
            config_json=gateway_config(),
            transport=gateway.transport(),
            evidence_cache=ProbeEvidenceCache(),
            project_admission=None,
        )

    with pytest.raises(LiteLLMGatewayError) as factory_denial:
        get_provider(
            provider_name="litellm",
            driver="litellm_gateway",
            endpoint_url=BASE_URL,
            api_key=VIRTUAL_KEY,
            config_json=gateway_config(),
        )

    for denial in (driver_denial.value, factory_denial.value):
        assert denial.gateway_state == GATEWAY_STATE_ALIAS_DENIED
        assert denial.denial_reason == "project_policy_context_missing"
        assert classify_runtime_error(denial).error_class == RUNTIME_ERROR_ALIAS_DENIED
    assert gateway.requests == []


async def test_provider_factory_passes_the_verified_admission_to_the_driver() -> None:
    admission = verified_admission(ALIAS)

    client = get_provider(
        provider_name="litellm",
        driver="litellm_gateway",
        endpoint_url=BASE_URL,
        api_key=VIRTUAL_KEY,
        config_json=gateway_config(),
        project_model_admission=admission,
    )
    try:
        assert isinstance(client, LiteLLMGatewayClient)
        assert client.project_admission is admission
    finally:
        await client.close()


async def test_worker_path_client_kwargs_cannot_dispatch_through_the_gateway(gateway, build_gateway_client) -> None:
    """Provider-scoped kwargs (model sync, knowledge/worker/tool paths) deny dispatch.

    ``build_provider_client_kwargs`` knows a provider row, not a project, so it
    attaches the unverified admission: the catalog stays readable while every
    chat dispatch is refused with zero requests.
    """

    kwargs = build_provider_client_kwargs(gateway_provider())
    assert kwargs[PROJECT_ADMISSION_KWARG] is UNVERIFIED_PROJECT_ADMISSION

    client = build_gateway_client(gateway, project_admission=kwargs[PROJECT_ADMISSION_KWARG])

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)
    # The provider catalog is still readable for model sync.
    catalog = await client.list_models()

    assert excinfo.value.gateway_state == GATEWAY_STATE_ALIAS_DENIED
    assert excinfo.value.denial_reason == "project_policy_context_unverifiable"
    assert gateway.chat_requests == []
    assert catalog[0]["id"] == ALIAS


def test_client_kwargs_leave_other_drivers_untouched() -> None:
    kwargs = build_provider_client_kwargs(
        gateway_provider(name="openai_compatible", driver="openai_compatible")
    )

    assert PROJECT_ADMISSION_KWARG not in kwargs


def test_virtual_key_is_absent_from_config_repr_and_evidence(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway)

    assert VIRTUAL_KEY not in repr(client.config)
    assert VIRTUAL_KEY not in str(client.config.evidence())
    assert VIRTUAL_KEY not in str(client.config.raw_config)


def test_non_injected_client_refuses_environment_trust_and_redirects(
    gateway,
    build_gateway_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real (non-test) transport path must not read proxy/TLS env variables.

    With httpx's default ``trust_env=True`` an ambient HTTPS_PROXY mounts a proxy
    transport, and the ``Authorization: Bearer <virtual key>`` header would be
    sent to whatever host that variable names.
    """

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.attacker.test:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.attacker.test:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.attacker.test:8080")

    transport_client = build_gateway_client(gateway, transport=None).client._client

    assert transport_client.trust_env is False
    assert transport_client.follow_redirects is False
    # No env-derived proxy transport was mounted for this client.
    assert transport_client._mounts == {}


def test_injected_transport_stays_testable_and_keeps_the_boundary(
    gateway,
    build_gateway_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    real_async_client = httpx.AsyncClient

    def _recording_async_client(**kwargs: Any) -> httpx.AsyncClient:
        captured.update(kwargs)
        return real_async_client(**kwargs)

    monkeypatch.setattr(
        "app.services.model_gateway.litellm.client.httpx.AsyncClient",
        _recording_async_client,
    )

    client = build_gateway_client(gateway)

    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    assert captured["transport"] is not None
    assert client.client._client.trust_env is False
