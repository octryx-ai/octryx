from pydantic import ValidationError

from app.runtime_limits import MAX_LLM_CACHE_TTL_SECONDS, MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS
from app.schemas.admin.admin_runtime_panel import (
    ContextBudgetProfileUpsertRequest,
    CopilotDevicePollRequest,
    RuntimeDirectionRequest,
    RuntimeSettingsUpdateRequest,
    ToolResultCompressorUpdateRequest,
)


def test_runtime_request_defaults_and_bounds_remain_stable():
    runtime_payload = RuntimeSettingsUpdateRequest(
        runtime_request_timeout_seconds=MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        llm_cache_ttl_seconds=MAX_LLM_CACHE_TTL_SECONDS,
    )
    direction_payload = RuntimeDirectionRequest()
    budget_payload = ContextBudgetProfileUpsertRequest(
        name="Incident mode",
        trigger_pattern="incident",
        base_budget=4000,
    )
    compressor_payload = ToolResultCompressorUpdateRequest(strategy="compact")

    assert runtime_payload.runtime_request_timeout_seconds == MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS
    assert runtime_payload.llm_cache_ttl_seconds == MAX_LLM_CACHE_TTL_SECONDS
    # Undeclared keys reach the service verbatim, even as null, so a retired key is refused, not dropped.
    retired_write = RuntimeSettingsUpdateRequest.model_validate({"edit_model": None, "trace_max_string": None})
    assert retired_write.to_update_payload() == {"edit_model": None}
    assert direction_payload.direction == "up"
    assert budget_payload.priority == 100
    assert compressor_payload.config == {}

    try:
        CopilotDevicePollRequest(flow_id="")
    except ValidationError as exc:
        assert "flow_id" in str(exc)
    else:
        raise AssertionError("Expected poll request validation to reject empty flow ids")
