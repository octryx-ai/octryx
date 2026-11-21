"""Transport failures of provider clients are typed by exception type (roadmap 3, R2).

A connect error, a timeout, or a connection closed mid-response leaves the
provider client as a ``ProviderRuntimeError`` whose class comes from the exception
type and whose audited classification source is ``exception_type``. The Work
Strategy alias failover switches only on such typed transient classes, so a
gateway that is down now fails over instead of ending the node.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.agent.core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    ProviderRuntimeError,
    classify_runtime_error,
)
from app.agent.engine.runtime._engine_runtime_fallback import _chat_with_runtime_fallback
from app.agent.providers import OpenAICompatibleClient
from app.services.governed_agent_run.model_failover import (
    AliasChain,
    ModelFailover,
    dispatch_with_failover,
)
from app.services.model_gateway.litellm.errors import LiteLLMGatewayError, gateway_transport_error

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

_HOST = "gateway.internal.test"
_MESSAGES = [{"role": "user", "content": "hello"}]
_ANSWER = {"choices": [{"message": {"content": "served"}}], "model": "backup"}

TRANSPORT_CASES = [
    (httpx.ConnectError(f"connect to {_HOST} failed"), "unreachable"),
    (httpx.ConnectTimeout(f"connect to {_HOST} timed out"), "timeout"),
    (httpx.ReadTimeout("read timed out"), "timeout"),
    (httpx.RemoteProtocolError("Server disconnected without sending a response."), "transient"),
]


def _client(outcome: Exception | dict[str, Any]) -> OpenAICompatibleClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(200, json=outcome, request=request)

    client = OpenAICompatibleClient(base_url=f"http://{_HOST}/v1", api_key="test-key")
    client.client = httpx.AsyncClient(base_url=f"http://{_HOST}/v1", transport=httpx.MockTransport(handle))
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(("exc", "expected_class"), TRANSPORT_CASES)
async def test_openai_compatible_transport_failure_is_typed_by_exception_type(exc, expected_class) -> None:
    with pytest.raises(ProviderRuntimeError) as excinfo:
        await _client(exc).chat(messages=_MESSAGES, model="primary")

    classification = classify_runtime_error(excinfo.value)
    assert (classification.error_class, classification.source) == (expected_class, CLASSIFICATION_SOURCE_EXCEPTION_TYPE)
    # A fixed message: the exception type, never the transport's own text.
    assert str(excinfo.value) == f"OpenAI-compatible API transport failure ({type(exc).__name__})"
    assert _HOST not in str(excinfo.value)


@pytest.mark.parametrize(
    ("exc", "state", "expected_class"),
    [
        (httpx.ConnectError("x"), "gateway_unreachable", "unreachable"),
        (httpx.ReadTimeout("x"), "gateway_timeout", "timeout"),
        (httpx.RemoteProtocolError("x"), "gateway_unavailable", "transient"),
    ],
)
def test_gateway_transport_failure_is_typed_by_exception_type(exc, state, expected_class) -> None:
    error = gateway_transport_error(exc)

    assert isinstance(error, LiteLLMGatewayError)
    assert error.gateway_state == state
    classification = classify_runtime_error(error)
    assert (classification.error_class, classification.source) == (expected_class, CLASSIFICATION_SOURCE_EXCEPTION_TYPE)


def test_raw_transport_exceptions_classify_by_type_not_by_message() -> None:
    # A transport exception that reached the engine unwrapped is still typed, and a
    # message that merely mentions a connection problem is not.
    assert classify_runtime_error(httpx.ConnectError("")).source == CLASSIFICATION_SOURCE_EXCEPTION_TYPE
    assert classify_runtime_error(RuntimeError("connection refused")).error_class == "permanent"


def _runtime(alias: str) -> dict[str, Any]:
    return {
        "provider_name": f"gateway-{alias}",
        "model": alias,
        "target_id": f"target-{alias}",
        "priority": 1,
        "max_runtime_retries": 0,
        "max_context_retries": 0,
        "max_malformed_retries": 0,
    }


@pytest.mark.asyncio
async def test_a_connect_error_on_the_first_alias_fails_over_to_the_next() -> None:
    outcomes: dict[str, Exception | dict[str, Any]] = {
        "primary": httpx.ConnectError(f"connect to {_HOST} failed"),
        "backup": _ANSWER,
    }
    served: list[str] = []

    def get_provider(**kwargs):
        return _client(outcomes[str(kwargs.get("provider_name")).removeprefix("gateway-")])

    async def dispatch(chain: AliasChain):
        served.append(chain.alias)
        response, runtime, _attempts = await _chat_with_runtime_fallback(
            list(chain.runtimes),
            messages=_MESSAGES,
            tools=None,
            get_provider_func=get_provider,
            retry_policy={"max_retries": 0, "pause_seconds": 0},
        )
        return response, runtime

    async def before_switch(_chain: AliasChain) -> None:
        return None

    switches: list[ModelFailover] = []
    chains = (AliasChain("primary", (_runtime("primary"),)), AliasChain("backup", (_runtime("backup"),)))
    response, runtime = await dispatch_with_failover(
        chains, start=0, dispatch=dispatch, before_switch=before_switch, on_switch=switches.append
    )

    assert response["content"] == "served"
    assert runtime["model"] == "backup"
    assert served == ["primary", "backup"]
    assert switches == [ModelFailover("primary", "backup", "unreachable", CLASSIFICATION_SOURCE_EXCEPTION_TYPE)]
