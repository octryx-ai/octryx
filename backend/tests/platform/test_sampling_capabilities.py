"""The sampling capability catalog: temperature 0 for every model that accepts one, none for the Claude 5
family, and a runtime target's ``accepts_temperature`` overrides the catalog."""

from __future__ import annotations

import pytest

from app.agent.providers.sampling_capabilities import model_accepts_temperature, sampling_temperature

REJECTING = (
    "claude-sonnet-5",
    "claude-opus-5-5",
    "claude-fable-5-1",
    "anthropic.claude-opus-5-5",
    "eu.anthropic.claude-sonnet-5-v1:0",
    "global.anthropic.claude-opus-5-5",
    "anthropic/claude-sonnet-5",
)
ACCEPTING = (
    "claude-sonnet-4-5",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-sonnet-50",
    "qwen.qwen3-32b-v1:0",
    "amazon.nova-pro-v1:0",
    "",
)


@pytest.mark.parametrize("model", REJECTING)
def test_claude_5_models_reject_an_explicit_temperature(model):
    assert model_accepts_temperature(model) is False
    assert sampling_temperature(model, None) is None
    assert sampling_temperature(model, 0.4) is None


@pytest.mark.parametrize("model", ACCEPTING)
def test_other_models_get_temperature_zero_unless_one_is_requested(model):
    assert model_accepts_temperature(model) is True
    assert sampling_temperature(model, None) == 0.0
    assert sampling_temperature(model, 0.4) == 0.4


def test_the_runtime_target_override_wins_over_the_catalog():
    assert sampling_temperature("claude-sonnet-4-5", None, override=False) is None
    assert sampling_temperature("claude-sonnet-5", None, override=True) == 0.0
    assert sampling_temperature("claude-sonnet-5", 0.7, override=True) == 0.7
