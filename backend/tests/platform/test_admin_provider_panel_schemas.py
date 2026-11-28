from pydantic import ValidationError

from app.runtime_limits import MAX_COMPLETION_TOKENS, MIN_COMPLETION_TOKENS
from app.schemas.admin.admin_provider_panel import (
    LocalBootstrapSetupRequest,
    ProviderModelCreateRequest,
    ProviderModelUpdateRequest,
)


def test_provider_model_requests_preserve_validation_bounds():
    request = ProviderModelCreateRequest(
        model_id="gpt-test",
        max_tokens_per_request=MIN_COMPLETION_TOKENS,
        pricing_input=3.0,
        pricing_output=15.0,
    )
    assert request.max_tokens_per_request == MIN_COMPLETION_TOKENS
    assert request.pricing_input == 3.0
    assert request.pricing_output == 15.0

    update = ProviderModelUpdateRequest(
        supports_tools=True,
        supports_vision=False,
    )
    assert update.supports_tools is True
    assert update.supports_vision is False

    try:
        ProviderModelUpdateRequest(
            max_tokens_per_request=MAX_COMPLETION_TOKENS + 1,
        )
    except ValidationError as exc:
        assert "max_tokens_per_request" in str(exc)
    else:
        raise AssertionError("Expected provider model update validation to reject an oversized output budget")

    try:
        ProviderModelUpdateRequest(pricing_input=-0.01)
    except ValidationError as exc:
        assert "pricing_input" in str(exc)
    else:
        raise AssertionError("Expected provider model update validation to reject negative pricing")


def test_local_bootstrap_setup_defaults_remain_stable():
    payload = LocalBootstrapSetupRequest()

    assert payload.model_id == "gemma4"
    assert payload.display_name == "Local Gemma 4 Anchor"
    assert payload.pull_model is True
    assert payload.make_primary is True
    assert payload.auto_start is True
