"""Check codes, reason codes and the constant probe request of the LiteLLM gateway qualification."""

from __future__ import annotations

import re
from typing import Any

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"

CHECK_CONTENT_LOGGING_POSTURE = "content_logging_posture"
CHECK_NETWORK_PATH_CONTRACT = "network_path_contract"
CHECK_CATALOG_PROBE = "catalog_probe_contract"
CHECK_CAPABILITY_PARITY = "model_info_capability_parity"
CHECK_USAGE_INTEGRAL = "integral_prompt_completion_usage"
CHECK_COST_CONTRACT = "cost_contract"
CHECK_MODEL_GROUP_IDENTITY = "governed_model_group_identity"

# Fail-closed checks. Each one drives a response the gateway must refuse.
FAIL_CLOSED_MODEL_GROUP_MISMATCH = "fail_closed_model_group_mismatch"
FAIL_CLOSED_USAGE_NOT_REPORTED = "fail_closed_usage_not_reported"
FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE = "fail_closed_gateway_reported_cost_not_positive"
FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST = "fail_closed_governed_free_reported_cost"
FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE = "fail_closed_catalog_pricing_cost_not_positive"
FAIL_CLOSED_CAPABILITY_NOT_PROVEN = "fail_closed_capability_not_proven"

REQUIRED_CHECK_CODES = (
    CHECK_CONTENT_LOGGING_POSTURE,
    CHECK_NETWORK_PATH_CONTRACT,
    CHECK_CATALOG_PROBE,
    CHECK_CAPABILITY_PARITY,
    CHECK_USAGE_INTEGRAL,
    CHECK_COST_CONTRACT,
    CHECK_MODEL_GROUP_IDENTITY,
)
REQUIRED_FAIL_CLOSED_CODES = (
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    FAIL_CLOSED_USAGE_NOT_REPORTED,
    FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
    FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
    FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE,
    FAIL_CLOSED_CAPABILITY_NOT_PROVEN,
)

EVIDENCE_ORIGIN_LOCAL_FIXTURE = "local_contract_fixture"
EVIDENCE_ORIGIN_EXTERNAL_LIVE = "external_live_gateway"
EVIDENCE_ORIGINS = frozenset({EVIDENCE_ORIGIN_LOCAL_FIXTURE, EVIDENCE_ORIGIN_EXTERNAL_LIVE})

LIVE_EVIDENCE_PENDING_EXTERNAL_GATE = "pending_external_gate"
LIVE_EVIDENCE_CONFIRMED = "external_live_gateway_confirmed"

# What protects the virtual key on the wire, as a closed code. Only the first is
# a TLS chain this client verified; the other two say plainly that it is not.
TRANSPORT_ASSURANCE_VERIFIED_TLS = "verified_tls_chain"
TRANSPORT_ASSURANCE_ATTESTED_NODE_ENCRYPTION = "operator_attested_node_encryption"
TRANSPORT_ASSURANCE_LOOPBACK_PLAINTEXT = "loopback_plaintext"

# Detail reason codes produced by this module.
REASON_DECLARED_CAPABILITY_NOT_PROVEN = "declared_capability_not_proven"
REASON_DECLARED_CAPABILITY_REFUTED = "declared_capability_refuted"
REASON_CONTEXT_LIMIT_ABOVE_PROBE_MAX_INPUT = "context_limit_above_probe_max_input_tokens"
REASON_MODEL_GROUP_ABSENT_FROM_CATALOG = "model_group_absent_from_catalog"
REASON_CATALOG_REPORTS_NO_MODEL_GROUP = "catalog_reports_no_model_group"
REASON_POSTURE_NOT_LIVE_VERIFIED = "content_logging_posture_not_live_verified"
REASON_ORIGIN_NOT_EXTERNAL_LIVE = "evidence_origin_not_external_live_gateway"
REASON_LOOPBACK_ENDPOINT_NOT_SHARED = "loopback_endpoint_is_not_a_shared_gateway"
REASON_PLAINTEXT_TRANSPORT_NOT_SHARED = "plaintext_transport_is_not_a_shared_gateway"
REASON_COST_NOT_FINITE = "cost_not_finite"
REASON_COST_NOT_POSITIVE = "cost_not_positive"
REASON_COST_NOT_ZERO = "cost_not_zero"
REASON_COST_SOURCE_MISMATCH = "cost_source_mismatch"
REASON_TOKENS_NOT_INTEGRAL = "tokens_not_integral"
REASON_PROMPT_TOKENS_NOT_POSITIVE = "prompt_tokens_not_positive"
REASON_MODEL_GROUP_NOT_VERIFIED = "model_group_not_verified"
REASON_NETWORK_PATH_PORT_UNRESOLVED = "network_path_port_unresolved"
REASON_RESPONSE_ACCEPTED = "response_accepted_instead_of_refused"
REASON_UNEXPECTED_GATEWAY_STATE = "unexpected_gateway_state"
REASON_UNEXPECTED_DENIAL_REASON = "unexpected_denial_reason"
REASON_ERROR_CARRIES_CAUSE = "error_carries_exception_chain"

# The qualification prompt is a constant owned here: no caller can push tenant
# content through the qualification path, and no prompt text can reach evidence.
QUALIFICATION_MESSAGES: tuple[dict[str, Any], ...] = ({"role": "user", "content": "ping"},)
QUALIFICATION_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {"name": "qualification_noop", "description": "No-op.", "parameters": {}},
    },
)
QUALIFICATION_REASONING_EFFORT = "low"

_CODE_RE = re.compile(r"^[a-z0-9_.:-]{1,80}$")
# Pinned request paths are the one non-code string shape a detail may carry. The
# leading slash plus the absence of ``:`` keeps a URL from ever matching.
_PATH_RE = re.compile(r"^/[a-z0-9/_-]{0,79}$")
