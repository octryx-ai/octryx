"""Bedrock maps boto client error codes and botocore connection errors to explicit runtime error classes."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError

from app.agent.core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    CLASSIFICATION_SOURCE_EXPLICIT,
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    RUNTIME_ERROR_UNREACHABLE,
    ProviderRuntimeError,
    classify_runtime_error,
)
from app.agent.providers import BedrockClient
from tests.provider_runtime_error_adoption_support import _MESSAGES

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")


def _bedrock_client_error(code: str, http_status: int, message: str = "upstream detail") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": http_status},
        },
        "Converse",
    )


class _FakeBedrockConverseClient:
    """boto3 bedrock-runtime client stand-in whose converse() raises one canned exception."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def converse(self, **kwargs):
        raise self._exc


def _bedrock_client_with(exc: Exception) -> BedrockClient:
    client = BedrockClient(region="eu-central-1")
    client._client = _FakeBedrockConverseClient(exc)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "http_status", "expected_class"),
    [
        ("ThrottlingException", 429, RUNTIME_ERROR_TRANSIENT),
        ("TooManyRequestsException", 429, RUNTIME_ERROR_TRANSIENT),
        ("ServiceQuotaExceededException", 429, RUNTIME_ERROR_TRANSIENT),
        ("ServiceUnavailableException", 503, RUNTIME_ERROR_TRANSIENT),
        ("InternalServerException", 500, RUNTIME_ERROR_TRANSIENT),
        ("ModelTimeoutException", 408, RUNTIME_ERROR_TIMEOUT),
        # Bedrock has no structured signal for context overflow (message text
        # only), so ValidationException deterministically maps to permanent.
        ("ValidationException", 400, RUNTIME_ERROR_PERMANENT),
        ("AccessDeniedException", 403, RUNTIME_ERROR_PERMANENT),
        ("UnauthorizedException", 401, RUNTIME_ERROR_PERMANENT),
        ("ResourceNotFoundException", 404, RUNTIME_ERROR_PERMANENT),
        ("ModelNotReadyException", 429, RUNTIME_ERROR_PERMANENT),
    ],
)
async def test_bedrock_chat_maps_client_error_code_to_explicit_error_class(error_code, http_status, expected_class):
    client = _bedrock_client_with(_bedrock_client_error(error_code, http_status))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic.claude-3-5-sonnet-20241022:0")

    assert excinfo.value.runtime_error_class == expected_class
    assert excinfo.value.status_code == http_status
    assert f"Bedrock Converse API error ({error_code})" in str(excinfo.value)
    assert "upstream detail" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ClientError)


@pytest.mark.asyncio
async def test_bedrock_chat_maps_unknown_client_error_code_to_permanent_without_status():
    exc = ClientError({"Error": {"Code": "SomeNewException", "Message": "boom"}}, "Converse")
    client = _bedrock_client_with(exc)

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic.claude-3-5-sonnet-20241022:0")

    assert excinfo.value.runtime_error_class == RUNTIME_ERROR_PERMANENT
    assert excinfo.value.status_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "expected_class"),
    [
        (ConnectTimeoutError(endpoint_url="https://bedrock-runtime.test"), RUNTIME_ERROR_TIMEOUT),
        (ReadTimeoutError(endpoint_url="https://bedrock-runtime.test"), RUNTIME_ERROR_TIMEOUT),
        (EndpointConnectionError(endpoint_url="https://bedrock-runtime.test"), RUNTIME_ERROR_UNREACHABLE),
    ],
)
async def test_bedrock_chat_maps_botocore_connection_errors_by_exception_type(exc, expected_class):
    client = _bedrock_client_with(exc)

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic.claude-3-5-sonnet-20241022:0")

    assert excinfo.value.runtime_error_class == expected_class
    assert excinfo.value.status_code is None
    # The fixed message names the exception type, never the endpoint.
    assert "bedrock-runtime.test" not in str(excinfo.value)
    assert type(exc).__name__ in str(excinfo.value)
    assert classify_runtime_error(excinfo.value).source == CLASSIFICATION_SOURCE_EXCEPTION_TYPE


@pytest.mark.asyncio
async def test_bedrock_client_errors_classify_with_explicit_source():
    client = _bedrock_client_with(_bedrock_client_error("ThrottlingException", 429, "Rate exceeded"))

    with pytest.raises(ProviderRuntimeError) as excinfo:
        await client.chat(messages=_MESSAGES, model="anthropic.claude-3-5-sonnet-20241022:0")

    classification = classify_runtime_error(excinfo.value)
    assert classification.error_class == RUNTIME_ERROR_TRANSIENT
    assert classification.source == CLASSIFICATION_SOURCE_EXPLICIT
