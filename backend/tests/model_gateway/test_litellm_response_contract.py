"""Response contract: what the gateway serves is checked before it is accepted.

The pinned contract covers the model group, the HTTP state, redirects, usage,
and cost. A response whose price or token usage cannot be established is
discarded rather than billed silently at zero, and no response body, header, or
transport text ever reaches an error message.
"""

from __future__ import annotations

import httpx
import pytest

from app.agent.core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXPLICIT,
    NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES,
    RUNTIME_ERROR_FALLBACK_VIOLATION,
    RUNTIME_ERROR_PROVIDER_INIT,
    classify_runtime_error,
)
from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.client import ENDPOINT_DENIAL_REDIRECTED
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RATE_LIMITED,
    GATEWAY_STATE_REQUEST_REJECTED,
    GATEWAY_STATE_UNAUTHORIZED,
    GATEWAY_STATE_UNAVAILABLE,
)
from tests.model_gateway.conftest import (
    ALIAS,
    BASE_URL,
    MESSAGES,
    VIRTUAL_KEY,
    FakeLiteLLMGateway,
    chat_body,
    gateway_config,
    verified_admission,
)

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

# A body that would leak the virtual key, the tenant, and the upstream error
# code if any of them were ever interpolated into a message.
SECRET_BODY = {
    "error": {
        "code": "invalid_api_key",
        "message": f"key {VIRTUAL_KEY} rejected for team alpha",
        "metadata": {"authorization": f"Bearer {VIRTUAL_KEY}"},
    }
}


HTTP_FAILURE_STATES = {
    401: GATEWAY_STATE_UNAUTHORIZED,
    403: GATEWAY_STATE_UNAUTHORIZED,
    429: GATEWAY_STATE_RATE_LIMITED,
    422: GATEWAY_STATE_REQUEST_REJECTED,
    500: GATEWAY_STATE_UNAVAILABLE,
    503: GATEWAY_STATE_UNAVAILABLE,
}


# Every redirect status, including the ones that historically changed the method.
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


REDIRECT_TARGET = "https://litellm.redirected.attacker.test/v1/chat/completions"


async def test_response_naming_another_model_group_is_a_fallback_violation(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(chat_payload=chat_body(model="some-other-group"))
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    error = excinfo.value
    assert error.gateway_state == GATEWAY_STATE_FALLBACK_VIOLATION
    assert classify_runtime_error(error).error_class == RUNTIME_ERROR_FALLBACK_VIOLATION
    assert classify_runtime_error(error).source == CLASSIFICATION_SOURCE_EXPLICIT
    # The response content is discarded, never surfaced through the error.
    assert "gateway answer" not in str(error)
    assert "some-other-group" not in str(error)
    assert error.__cause__ is None and error.__context__ is None


async def test_http_failures_map_to_fixed_states_without_leaking_the_body(build_gateway_client) -> None:
    observed: dict[int, str] = {}

    for status in HTTP_FAILURE_STATES:
        gateway = FakeLiteLLMGateway(chat_status=status, chat_payload=SECRET_BODY)
        client = build_gateway_client(gateway)

        with pytest.raises(LiteLLMGatewayError) as excinfo:
            await client.chat(MESSAGES, model=ALIAS)

        error = excinfo.value
        message = str(error)
        observed[status] = error.gateway_state
        assert error.status_code == status
        assert VIRTUAL_KEY not in message
        assert "team alpha" not in message
        assert "invalid_api_key" not in message
        assert "Bearer" not in message
        # No exception chaining: a transport/HTTP exception must not ride along.
        assert error.__cause__ is None and error.__context__ is None

    assert observed == HTTP_FAILURE_STATES


async def test_a_redirected_chat_endpoint_is_a_pre_dispatch_configuration_state(build_gateway_client) -> None:
    """A 3xx is a pinned endpoint pointing elsewhere: refused, never followed.

    The response carries a *valid* chat body, so a code path that accepted
    redirect content would return an answer here. It must not: nothing was
    served by the admitted endpoint, the ``Location`` header names a host the
    allowlist never approved, and the state stays fallbackable because no
    billable request succeeded.
    """

    observed: dict[int, tuple[str, str]] = {}

    for status in REDIRECT_STATUSES:
        gateway = FakeLiteLLMGateway(chat_status=status, response_headers={"Location": REDIRECT_TARGET})
        client = build_gateway_client(gateway)

        with pytest.raises(LiteLLMGatewayError) as excinfo:
            await client.chat(MESSAGES, model=ALIAS)

        error = excinfo.value
        observed[status] = (error.gateway_state, error.denial_reason)
        assert error.status_code == status
        # The redirect was not followed: exactly one request, to the pinned host.
        assert len(gateway.chat_requests) == 1
        assert gateway.chat_requests[0].url.host == httpx.URL(BASE_URL).host
        # Neither the redirect target nor the response content is surfaced.
        for leak in (REDIRECT_TARGET, "redirected.attacker.test", "gateway answer", "Location"):
            assert leak not in str(error)
            assert leak not in str(error.evidence())
        assert error.__cause__ is None and error.__context__ is None
        # Pre-dispatch configuration states stay fallbackable.
        assert classify_runtime_error(error).error_class == RUNTIME_ERROR_PROVIDER_INIT
        assert RUNTIME_ERROR_PROVIDER_INIT not in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES

    assert observed == {
        status: (GATEWAY_STATE_CONFIGURATION_INVALID, ENDPOINT_DENIAL_REDIRECTED) for status in REDIRECT_STATUSES
    }


async def test_a_redirected_catalog_probe_is_a_typed_configuration_failure(build_gateway_client) -> None:
    from app.services.provider.model_sync import ModelCatalogSyncError

    gateway = FakeLiteLLMGateway(catalog_status=307, response_headers={"Location": REDIRECT_TARGET})
    client = build_gateway_client(gateway)

    with pytest.raises(ModelCatalogSyncError) as excinfo:
        await client.list_models()

    error = excinfo.value
    assert error.sync_state == "validation_failed"
    assert error.error_class == f"{GATEWAY_STATE_CONFIGURATION_INVALID}:{ENDPOINT_DENIAL_REDIRECTED}"
    assert "redirected.attacker.test" not in str(error)
    assert len(gateway.requests) == 1


async def test_context_length_error_code_becomes_context_pressure(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(
        chat_status=400,
        chat_payload={"error": {"code": "context_length_exceeded", "message": "prompt too long"}},
    )
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model=ALIAS)

    assert excinfo.value.gateway_state == "context_pressure"
    assert "prompt too long" not in str(excinfo.value)


async def test_transport_failures_do_not_chain_the_transport_exception() -> None:
    from app.agent.providers.litellm_gateway import LiteLLMGatewayClient
    from app.services.model_gateway.litellm.capability_evidence import ProbeEvidenceCache

    def _handle(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect to 10.0.0.1:4000 failed")

    client = LiteLLMGatewayClient(
        endpoint_url=BASE_URL,
        api_key=VIRTUAL_KEY,
        config_json=gateway_config(),
        transport=httpx.MockTransport(_handle),
        evidence_cache=ProbeEvidenceCache(),
        project_admission=verified_admission(ALIAS),
    )
    try:
        with pytest.raises(LiteLLMGatewayError) as excinfo:
            await client.chat(MESSAGES, model=ALIAS)
    finally:
        await client.close()

    assert "10.0.0.1" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__context__ is None
