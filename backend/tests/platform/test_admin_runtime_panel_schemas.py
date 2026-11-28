from pydantic import ValidationError

from app.runtime_limits import MAX_APPROX_CHARS_PER_TOKEN, MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS
from app.schemas.admin.admin_runtime_panel import (
    CopilotDevicePollRequest,
    RuntimeDirectionRequest,
    RuntimeSettingsUpdateRequest,
)


def test_runtime_request_defaults_and_bounds_remain_stable():
    runtime_payload = RuntimeSettingsUpdateRequest(
        runtime_request_timeout_seconds=MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        approx_chars_per_token=MAX_APPROX_CHARS_PER_TOKEN,
    )
    direction_payload = RuntimeDirectionRequest()

    assert runtime_payload.runtime_request_timeout_seconds == MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS
    assert runtime_payload.approx_chars_per_token == MAX_APPROX_CHARS_PER_TOKEN
    # Undeclared keys reach the service verbatim, even as null, so a retired key is refused, not dropped.
    retired_write = RuntimeSettingsUpdateRequest.model_validate({"edit_model": None, "trace_max_string": None})
    assert retired_write.to_update_payload() == {"edit_model": None}
    assert direction_payload.direction == "up"

    try:
        CopilotDevicePollRequest(flow_id="")
    except ValidationError as exc:
        assert "flow_id" in str(exc)
    else:
        raise AssertionError("Expected poll request validation to reject empty flow ids")
