"""Names, headers and fixed states shared by the gateway routes, the launcher and the model gateway."""

from __future__ import annotations

GATEWAY_AUDIENCE = "octryx-model-gateway"
SCOPE_MODEL_INVOKE = "model:invoke"

HEADER_SESSION = "x-octryx-session"
HEADER_WORKSPACE = "x-octryx-workspace"
HEADER_WORK_ITEM = "x-octryx-work-item"
# The workflow run a device job works on; verified on the server before the session binds to it.
HEADER_WORKFLOW_RUN = "x-octryx-workflow-run"

# The seat profile's model route: its bearer is the user's own subscription token, never an
# Octryx token, so nothing decodes it as one.
SEAT_MODEL_ROUTE_PREFIX = "/api/v1/model-gateway/anthropic/seat/"
# The Codex seat's model route: its bearer is the person's own ChatGPT token (``inbound/codex_seat``).
CODEX_SEAT_MODEL_ROUTE_PREFIX = "/api/v1/model-gateway/openai/seat/"
SEAT_MODEL_ROUTE_PREFIXES = (SEAT_MODEL_ROUTE_PREFIX, CODEX_SEAT_MODEL_ROUTE_PREFIX)

HEADER_GATEWAY_STATE = "x-octryx-gateway-state"
HEADER_GATEWAY_REASON = "x-octryx-gateway-reason"

STATE_ALLOWED = "allowed"
STATE_DENIED = "denied"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_UNAUTHORIZED = "unauthorized"

REASON_TOKEN_MISSING = "gateway_token_missing"
REASON_TOKEN_INVALID = "gateway_token_invalid"
REASON_SCOPE_MISSING = "gateway_scope_missing"
REASON_USER_INACTIVE = "gateway_user_inactive"
REASON_SESSION_HEADER_MISSING = "session_header_missing"
REASON_SESSION_HEADER_INVALID = "session_header_invalid"
REASON_WORKSPACE_NOT_SELECTED = "workspace_not_selected"
REASON_WORKSPACE_NOT_AUTHORIZED = "workspace_not_authorized"
REASON_SESSION_WORKSPACE_MISMATCH = "session_workspace_mismatch"
REASON_SESSION_OWNER_MISMATCH = "session_owner_mismatch"
REASON_SESSION_NOT_FOUND = "session_not_found"

EXTERNAL_AGENT_TYPE = "external_agent"
GATEWAY_EXTERNAL_SOURCE = "octryx_claude"
GATEWAY_CLIENT = "claude_code"
SESSION_KEY_METADATA = "gateway_session_key"

TOOL_CALL_SOURCE_GATEWAY = "model_gateway"
TOOL_CALL_SOURCE_HOOK = "client_hook"
TOOL_CALL_STATUS_REQUESTED = "requested"
TOOL_CALL_STATUS_SUCCESS = "success"
TOOL_CALL_STATUS_ERROR = "error"
TOOL_CALL_STATUS_DENIED = "denied_by_policy"
TOOL_CALL_EXECUTED_KEY = "executed"
EXECUTION_OUTCOME_SUCCEEDED = "succeeded"
EXECUTION_OUTCOME_FAILED = "failed"

__all__ = [name for name in dir() if name.isupper()]
