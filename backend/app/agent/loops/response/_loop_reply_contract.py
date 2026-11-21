"""The selected agent's checked reply contract at the runtime boundary.

An agent replies in free text unless its definition declares ``replyContract`` ``json_object``
(``services/agent_reply_contract``). For such an agent:

- before any model call, an invalid stored contract, or a turn the check cannot cover (a workflow
  or coordinator turn ends through finals that are never checked; a flow-definition session
  replaces the loop entirely), holds the turn as
  ``needs_configuration`` (:func:`evaluate_reply_contract_admission`, recorded on the execution
  profile like the tool-setting decision);
- the final reply is checked once, right after the answer-evidence guard
  (:func:`handle_reply_contract_check`): replies with tool calls and non-final agent steps are never
  checked. A satisfied reply passes unchanged and its trace records the closed result
  (``agent_reply_contract``); a violated one ends the turn as ``stopped`` with the validator's closed
  code as the runtime stop reason. The user receives the model's exact reply: nothing is stripped,
  unfenced, repaired or retried, and no reminder turn runs.

Payloads without the key, and ``{"kind": "text"}``, are free text and pass untouched.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.services.agent_reply_contract_check import check_reply
from app.services.agent_reply_contract_schema import (
    KIND_JSON_OBJECT,
    REASON_CONTRACT_INVALID,
    REPLY_CONTRACT_PAYLOAD_KEY,
    STATUS_SATISFIED,
    ReplyContractError,
    normalize_reply_contract,
)

from ....services.session.turn_execution_snapshot import AGENT_REPLY_CONTRACT_KEY, with_runtime_stop

#: A ``json_object`` agent on a path whose final reply is never checked.
REASON_PATH_UNSUPPORTED = "agent_reply_contract_path_unsupported"
#: An Action turn of a ``json_object`` agent that ended without a checked, accepted final.
REASON_UNCHECKED = "agent_reply_contract_unchecked"
#: Execution-profile requirement key of the admission decision (next to the tool-setting decision).
REQUIREMENT_METADATA_KEY = "agent_reply_contract"
DECISION_SOURCE = "agent_reply_contract"
_COORDINATOR_STRATEGY = "coordinator"

_INVALID_TEXT = "This agent's reply format is not valid; an administrator must fix it before the agent can run."
_PATH_TEXT = (
    "This agent's replies are checked against a reply format, which workflow, coordinator "
    "and flow-definition turns cannot check yet. Run the agent without them, or set its "
    "reply format to free text."
)


def payload_reply_contract(agent_definition: Any) -> dict[str, Any] | None:
    """The enforced ``json_object`` contract of a selected agent payload; ``None`` for free text.

    A missing key is free text. A present value is validated as it is and an
    invalid one raises :class:`ReplyContractError`, so no caller reads it as free text.
    """
    if not isinstance(agent_definition, Mapping) or REPLY_CONTRACT_PAYLOAD_KEY not in agent_definition:
        return None
    contract = normalize_reply_contract(agent_definition[REPLY_CONTRACT_PAYLOAD_KEY])
    return contract if contract["kind"] == KIND_JSON_OBJECT else None


def declares_checked_reply(agent_definition: Any) -> bool:
    """True when the payload declares anything but free text: a valid ``json_object`` or an invalid value."""
    try:
        return payload_reply_contract(agent_definition) is not None
    except ReplyContractError:
        return True


@dataclass(frozen=True, slots=True)
class ReplyContractAdmission:
    allowed: bool
    reason_code: str | None = None
    reason: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason_code": self.reason_code}


def evaluate_reply_contract_admission(
    agent_definition: Any,
    execution_profile: Mapping[str, Any] | None,
    *,
    workflow_id: str | None = None,
    delegated_runtime: bool = False,
) -> ReplyContractAdmission | None:
    """Decide a turn before any model call; ``None`` for a free-text agent (nothing recorded).

    *workflow_id* is the turn's selected workflow (the strategy decision's), next to the profile's own.
    *delegated_runtime* is true when ``run_agent`` hands the turn to a runtime other than the loop after
    admission: a flow-definition session's orchestration (``agent/engine/__init__.py``).
    A selected agent without a workflow runs as ``specialist`` or ``direct`` and is checked.
    """
    try:
        if payload_reply_contract(agent_definition) is None:
            return None
    except ReplyContractError:
        return ReplyContractAdmission(False, REASON_CONTRACT_INVALID, _INVALID_TEXT)
    profile = execution_profile if isinstance(execution_profile, Mapping) else {}
    workflow_selected = bool(str(workflow_id or "").strip() or str(profile.get("workflow_id") or "").strip())
    if delegated_runtime or workflow_selected or profile.get("execution_strategy") == _COORDINATOR_STRATEGY:
        return ReplyContractAdmission(False, REASON_PATH_UNSUPPORTED, _PATH_TEXT)
    return ReplyContractAdmission(True)


def apply_reply_contract_admission_to_profile(
    execution_profile: dict[str, Any] | None, admission: ReplyContractAdmission | None
) -> dict[str, Any]:
    """Record the decision; a refused one blocks an ``allowed`` profile as ``needs_configuration``.

    A profile that is already blocked keeps its own, earlier decision (as for the tool setting).
    """
    from app.services.execution_profile_status import (
        EXECUTION_PROFILE_STATUS_ALLOWED,
        EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
    )

    profile = dict(execution_profile or {})
    if admission is None:
        return profile
    requirements = dict(profile.get("requirements") or {})
    requirements[REQUIREMENT_METADATA_KEY] = admission.to_metadata()
    profile["requirements"] = requirements
    if admission.allowed or profile.get("status") != EXECUTION_PROFILE_STATUS_ALLOWED:
        return profile
    profile["status"] = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    profile["decision_source"] = DECISION_SOURCE
    profile["reason"] = admission.reason
    profile["reason_code"] = admission.reason_code
    return profile


async def handle_reply_contract_check(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
    request_messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    runtime_settings: dict[str, Any],
    usage_model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    has_followup_steps: bool,
    agent_definition: Any,
    persist_traced_assistant_message: Callable[..., Any],
) -> dict[str, Any] | None:
    """Check a candidate final reply once; ``None`` passes it on, else the loop's ``return`` outcome."""
    if not isinstance(agent_definition, Mapping) or REPLY_CONTRACT_PAYLOAD_KEY not in agent_definition:
        return None
    # Only the current candidate's result may stand on the turn's context: never an earlier one's.
    context_snapshot.pop(AGENT_REPLY_CONTRACT_KEY, None)
    if tool_calls or has_followup_steps:
        return None
    result = check_reply(agent_definition[REPLY_CONTRACT_PAYLOAD_KEY], content)
    if result is None:
        return None
    context_snapshot[AGENT_REPLY_CONTRACT_KEY] = result
    if result["status"] == STATUS_SATISFIED:
        return None
    stop_reason = result["reason"]
    usage = response.get("usage", {})
    await persist_traced_assistant_message(
        db=db,
        session_id=session_id,
        # The model's exact reply is delivered; the stop says why it is not an accepted result.
        content=content,
        provider=runtime["provider_name"],
        model=usage_model,
        input_messages=request_messages,
        context_snapshot=with_runtime_stop(context_snapshot, stop_reason),
        tool_trace=[],
        raw_output={
            "content": content,
            "tool_calls": [],
            "runtime_attempts": runtime_attempts,
            "thinking": str(response.get("thinking") or ""),
        },
        usage=usage,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        trace_limits=runtime_settings,
        runtime_stop_reason=stop_reason,
    )
    await db.commit()
    return {"action": "return", "yield_content": content, "yield_model": usage_model}


__all__ = [
    "REASON_PATH_UNSUPPORTED",
    "REASON_UNCHECKED",
    "ReplyContractAdmission",
    "apply_reply_contract_admission_to_profile",
    "declares_checked_reply",
    "evaluate_reply_contract_admission",
    "handle_reply_contract_check",
    "payload_reply_contract",
]
