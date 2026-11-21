"""The LiteLLM gateway body honours the temperature choice.

The gateway never adds a temperature on its own (model default); the model's catalog value is sent exactly,
over the caller's; "never send" (``accepts_temperature=False``) omits even a caller's temperature.
"""

from __future__ import annotations

import json

import pytest

from tests.model_gateway.conftest import ALIAS

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

MESSAGES = [{"role": "user", "content": "hi"}]


def _sent(gateway) -> dict:
    return json.loads(gateway.chat_requests[-1].content)


async def test_the_target_value_is_sent_exactly(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway, target_temperature=1.25)
    await client.chat(MESSAGES, model=ALIAS)
    assert _sent(gateway)["temperature"] == 1.25
    await client.chat(MESSAGES, model=ALIAS, temperature=0.3)
    assert _sent(gateway)["temperature"] == 1.25


async def test_never_send_omits_every_temperature(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway, accepts_temperature=False, target_temperature=1.25)
    await client.chat(MESSAGES, model=ALIAS, temperature=0.3)
    assert "temperature" not in _sent(gateway)


async def test_the_model_default_sends_none_unless_the_caller_sets_one(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway, accepts_temperature=True)
    await client.chat(MESSAGES, model=ALIAS)
    assert "temperature" not in _sent(gateway)
    await client.chat(MESSAGES, model=ALIAS, temperature=0.3)
    assert _sent(gateway)["temperature"] == 0.3
