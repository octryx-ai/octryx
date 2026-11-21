"""The sanitized upstream cause of a failed gateway request.

The fixed error message stays fixed; the short ``safe_detail`` names the gateway state, the HTTP status and the
upstream's own error sentence, with every key, token and credential removed.
"""

from __future__ import annotations

import json

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError
from app.services.model_gateway.litellm.upstream_detail import (
    MAX_DETAIL_CHARS,
    sanitize_detail,
    upstream_error_detail,
)
from tests.model_gateway.conftest import ALIAS, MESSAGES, VIRTUAL_KEY, FakeLiteLLMGateway

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

AWS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
JWT = "eyJhb" + "GciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
LEAKS = (VIRTUAL_KEY, "virtual-key-value", AWS_KEY_ID, AWS_SECRET, JWT, "hunter2secret", "Bearer abc")


def _body(message: str) -> bytes:
    return json.dumps({"error": {"code": "bad_request", "message": message}}).encode()


async def test_a_rejected_request_carries_the_upstream_sentence_but_no_key(build_gateway_client) -> None:
    message = (
        f"litellm.BadRequestError: BedrockException - `temperature` is deprecated for this model. "
        f"key={VIRTUAL_KEY} Authorization: Bearer {VIRTUAL_KEY} aws {AWS_KEY_ID} secret {AWS_SECRET} "
        f"token {JWT} https://user:hunter2secret@proxy.example/x"
    )
    gateway = FakeLiteLLMGateway(chat_status=400, chat_payload={"error": {"code": "bad_request", "message": message}})
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as raised:
        await client.chat(MESSAGES, model=ALIAS)

    error = raised.value
    assert error.safe_detail.startswith("request_rejected (HTTP 400): litellm.BadRequestError")
    assert "`temperature` is deprecated for this model" in error.safe_detail
    for leak in LEAKS:
        assert leak not in error.safe_detail
    assert len(error.safe_detail) <= MAX_DETAIL_CHARS + 40  # the closed head plus the bounded upstream text
    assert "temperature" not in str(error)  # the message itself stays the fixed constant


async def test_a_body_without_an_error_sentence_still_names_state_and_status(build_gateway_client) -> None:
    gateway = FakeLiteLLMGateway(chat_status=503, chat_payload={"unexpected": True})
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as raised:
        await client.chat(MESSAGES, model=ALIAS)

    assert raised.value.safe_detail == "gateway_unavailable (HTTP 503)"


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2]", _body("x" * 10) * 3000])
def test_unreadable_or_oversized_bodies_contribute_nothing(raw: bytes) -> None:
    assert upstream_error_detail(raw) == ""


def test_the_sanitizer_keeps_model_ids_and_drops_credential_shapes() -> None:
    text = sanitize_detail(
        "Model claude-opus-5-5-20260101-v1 rejected: api_key=abc1" + "23def456 sk-ant-api03-ZXhhbXBsZWtleQ "
        "0123" + "456789abcdef0123456789abcdef MixedCaseToken9xYzAbCdEfGh1234\nnext line"
    )
    assert "claude-opus-5-5-20260101-v1" in text
    for leak in (
        ("abc1" + "23def456"),
        "sk-ant-api03",
        ("0123" + "456789abcdef0123456789abcdef"),
        "MixedCaseToken9xYz",
        "\n",
    ):
        assert leak not in text


def test_credential_material_the_patterns_miss_drops_the_whole_text() -> None:
    # Short JWT segments slip past the token-run rule; the gateway secret scan is the backstop. The known secret
    # forms (scripts/secret_patterns.py, after gitleaks) also redact a JWT themselves: it never reaches the text.
    jwt = "eyJhbGciOiJIUz.eyJzdWIiOiIxMj.abcdefghijklmnopq"
    detail = sanitize_detail(f"rejected token {jwt}")
    assert jwt not in detail and "eyJ" not in detail


def test_the_sanitizer_bounds_the_text() -> None:
    text = sanitize_detail("word " * 200)
    assert len(text) == MAX_DETAIL_CHARS and text.endswith("...")


def test_error_detail_falls_back_to_detail_or_message_keys() -> None:
    assert upstream_error_detail(json.dumps({"detail": "model not found"}).encode()) == "model not found"
    assert upstream_error_detail(json.dumps({"error": "quota exceeded"}).encode()) == "quota exceeded"


@pytest.mark.parametrize(
    "token",
    [
        "abcdefgh12345678ijklmn9",
        "lowercaseonlysecretvalue123",
        "0123456789abcdef0123",
        "0123456789abcdef01234",
        "0123456789abcdef012345",
        "0123456789abcdef0123456",
        "12345678901234567890",
        "abcd1234efgh5678",
        "model-abcdefgh12345678ijklmn9-v1",
    ],
)
def test_the_sanitizer_redacts_lowercase_and_hex_tokens(token: str) -> None:
    text = sanitize_detail(f"rejected credential {token} for this request")
    assert token not in text
    assert "[redacted]" in text or text == ""


@pytest.mark.parametrize(
    "model_id",
    [
        "claude-opus-5-5",
        "us.anthropic.claude-sonnet-5-20260101-v1:0",
        "gpt-4o-2024-08-06",
        "claude-opus-5-5-20260101-v1",
        "text-embedding-3-large",
    ],
)
def test_the_sanitizer_keeps_model_ids_readable(model_id: str) -> None:
    assert sanitize_detail(f"model {model_id} does not support temperature") == (
        f"model {model_id} does not support temperature"
    )
