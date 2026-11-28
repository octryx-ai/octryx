"""Transport failures of provider clients are typed by exception type, so the Work Strategy alias failover
switches on a gateway that is down instead of ending the node."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.agent.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    classify_runtime_error,
)
from app.agent.runtime.runtime_fallback import _chat_with_runtime_fallback
from app.services.governed_agent_run.model_failover import (
    AliasChain,
    ModelFailover,
    dispatch_with_failover,
)
from app.services.model_gateway.litellm.errors import LiteLLMGatewayError, gateway_transport_error

_HOST = "gateway.internal.test"
_MESSAGES = [{"role": "user", "content": "hello"}]
_ANSWER = {"content": "served", "tool_calls": None, "usage": {}, "model": "backup"}


# A gateway client whose transport fails the way ``litellm.client`` reports it.
class _Client:

    def __init__(self, outcome: Exception | dict[str, Any]) -> None:
        self.outcome = outcome

    async def chat(self, **_kwargs: Any) -> dict[str, Any]:
        if isinstance(self.outcome, Exception):
            raise gateway_transport_error(self.outcome)
        return dict(self.outcome)

    async def close(self) -> None:
        return None


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
        return _Client(outcomes[str(kwargs.get("provider_name")).removeprefix("gateway-")])

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
