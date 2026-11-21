"""Shared contract of the agent gateway (octryx-claude PoC).

External coding clients started through the ``octryx-claude`` launcher reach the
platform on two surfaces that share one identity:

- the inbound model route (``services/model_gateway/inbound``), which proxies the
  Anthropic Messages protocol to the governed LiteLLM data plane, and
- the client control plane (``api/routes/agent_gateway.py``), which the launcher's
  hooks call for local tool policy, the "done means verified" gate and session
  finalization.

Both authenticate with a platform OAuth access token minted for the
``octryx-model-gateway`` audience, name their Workspace and session with
explicit headers, and answer with explicit states. Nothing here guesses: a missing
header is ``needs_configuration``, never an implicit default.
"""

from __future__ import annotations

# OAuth resource indicator (RFC 8707) and scope for every gateway token. A token for
# any other audience (the MCP one, for example) is refused.
GATEWAY_AUDIENCE = "octryx-model-gateway"
SCOPE_MODEL_INVOKE = "model:invoke"

# Request headers the launcher sets for every model call (ANTHROPIC_CUSTOM_HEADERS)
# and every hook call.
HEADER_SESSION = "x-octryx-session"
HEADER_WORKSPACE = "x-octryx-workspace"
HEADER_WORK_ITEM = "x-octryx-work-item"
# The workflow run a device job works on; verified on the server before the session binds to it.
HEADER_WORKFLOW_RUN = "x-octryx-workflow-run"

# The seat profile's model route: its bearer is the user's own subscription token, never an
# Octryx token, so nothing decodes it as one (the RLS middleware skips it).
SEAT_MODEL_ROUTE_PREFIX = "/api/v1/model-gateway/anthropic/seat/"
# The Codex seat's model route: its bearer is the person's own ChatGPT token (``inbound/codex_seat``).
CODEX_SEAT_MODEL_ROUTE_PREFIX = "/api/v1/model-gateway/openai/seat/"
SEAT_MODEL_ROUTE_PREFIXES = (SEAT_MODEL_ROUTE_PREFIX, CODEX_SEAT_MODEL_ROUTE_PREFIX)
# Routes whose bearer is usually a gateway OAuth token (audience ``octryx-model-gateway``), which
# the RLS middleware cannot decode as a platform token: such a failure is expected there, not an error.
GATEWAY_ROUTE_PREFIXES = ("/api/v1/agent-gateway/", "/api/v1/model-gateway/")

# Response headers carrying the explicit gateway decision on a refusal.
HEADER_GATEWAY_STATE = "x-octryx-gateway-state"
HEADER_GATEWAY_REASON = "x-octryx-gateway-reason"

STATE_ALLOWED = "allowed"
STATE_DENIED = "denied"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_UNAUTHORIZED = "unauthorized"

# Identity refusal reasons (fixed codes, never interpolated).
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

# Shadow session identity. One platform Session per launcher session key.
EXTERNAL_AGENT_TYPE = "external_agent"
GATEWAY_EXTERNAL_SOURCE = "octryx_claude"
GATEWAY_CLIENT = "claude_code"
SESSION_KEY_METADATA = "gateway_session_key"

# ToolCall rows the inbound route records from the conversation it proxies.
# ``request_id`` holds the Anthropic ``tool_use`` id; ``parameters`` and ``result``
# follow the shapes below, bounded and redacted.
TOOL_CALL_SOURCE_GATEWAY = "model_gateway"
TOOL_CALL_SOURCE_HOOK = "client_hook"
TOOL_CALL_STATUS_REQUESTED = "requested"
TOOL_CALL_STATUS_SUCCESS = "success"
TOOL_CALL_STATUS_ERROR = "error"
TOOL_CALL_STATUS_DENIED = "denied_by_policy"
# parameters = {"source": TOOL_CALL_SOURCE_*, "tool_use_id": str, "input": dict (bounded,
#               redacted), "command": str (Bash only, bounded, redacted)}
# result     = {"is_error": bool, "excerpt": str (bounded, redacted)} once the matching
#               tool_result has been seen, else None
#
# Execution evidence (``POST sessions/tool-executed``, Claude Code's PostToolUse /
# PostToolUseFailure hooks for Bash): ``parameters["executed"] = {"outcome":
# "succeeded"|"failed", "source": "client_hook"}`` on the same model-gateway row. The
# hook normally arrives before the next model call carries the tool_use, so it may
# create the row first (only ``source``, ``tool_use_id`` and ``executed``); the model
# gateway then merges the tool_use fields into it. Neither writer overwrites the
# other's keys. No evidence means the tool never ran (refused before execution) or
# the client's hook did not report it.
TOOL_CALL_EXECUTED_KEY = "executed"
EXECUTION_OUTCOME_SUCCEEDED = "succeeded"
EXECUTION_OUTCOME_FAILED = "failed"

__all__ = [name for name in dir() if name.isupper()]
