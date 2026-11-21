"""Which approval rule a tool call falls under: the per-call rules and the project approval policy.

The policy identities and the exemption symmetry are described in ``tool_approval_gate``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tools.definitions import get_tool_definition_metadata
from ..tools.definitions.write_risk import OUTBOUND_MESSAGE_DEFINITION_NAMES
from .tool_approval_policy import effective_policy

RULE_OUTBOUND_MESSAGE = "outbound_message"
RULE_CHAT_CONNECTOR_WRITE = "chat_connector_write"
RULE_CHAT_PLATFORM_WRITE = "chat_platform_write"
RULE_UNATTENDED_EXTERNAL_WRITE = "unattended_external_write"
RULE_DEVICE_EXTERNAL_WRITE = "device_external_write"
# Rules that ask for every single call: no standing "always" rule answers them.
_PER_CALL_RULES = frozenset({RULE_OUTBOUND_MESSAGE, RULE_CHAT_CONNECTOR_WRITE, RULE_CHAT_PLATFORM_WRITE,
                             RULE_UNATTENDED_EXTERNAL_WRITE, RULE_DEVICE_EXTERNAL_WRITE})


@dataclass(frozen=True, slots=True)
class ToolApprovalSubject:
    """An explicit approval identity that overrides generic tool metadata."""

    subject_key: str
    risk: str
    display_name: str
    payload: dict[str, Any] | None = None
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolApprovalRequirement:
    tool_name: str
    required: bool
    reason: str
    matched_rule: str
    subject_key: str = ""
    risk: str = ""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "required": self.required,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "subject_key": self.subject_key or self.tool_name,
            "risk": self.risk,
        }


def _normalized_names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item or "").strip() for item in value if str(item or "").strip()}


def _policy_identity_risks(*identities: tuple[str, str]) -> dict[str, set[str]]:
    """Group the request's policy-addressable names to the risks each carries.

    The dispatched tool and an explicit subject can be the same name (direct FQN
    MCP dispatch); then that one identity carries both risks and an exemption
    waives both.
    """
    grouped: dict[str, set[str]] = {}
    for name, identity_risk in identities:
        if not name:
            continue
        risks = grouped.setdefault(name, set())
        if identity_risk:
            risks.add(identity_risk)
    return grouped


def tool_approval_requirement(
    tool_name: str,
    project_config: dict[str, Any] | None,
    *,
    subject: ToolApprovalSubject | None = None,
    chat_connector_write: bool = False,
    chat_platform_write: bool = False,
    unattended_external_write: bool = False,
    device_external_write: bool = False,
) -> ToolApprovalRequirement:
    """Return whether the project approval policy requires an approval for this tool.

    ``chat_connector_write`` / ``chat_platform_write``: the call is a connector or platform write from a chat turn
    (``chat_writes.py``); the person confirms it, whatever the policy says."""
    normalized_name = str(tool_name or "").strip()
    subject_key = str(subject.subject_key or "").strip() if subject is not None else ""
    # The platform default plus the Workspace's own rules (``tool_approval_policy``).
    policy = effective_policy(project_config if isinstance(project_config, dict) else {})
    # The dispatched tool's own risk stays a floor: an explicit subject may only
    # add a governed risk, never lower an existing project rule's reach.
    definition_risk = str(get_tool_definition_metadata(normalized_name).risk or "").strip().lower()
    subject_risk = str(subject.risk or "").strip().lower() if subject is not None else ""
    risk = subject_risk or definition_risk
    forced = _per_call_requirement(
        normalized_name,
        policy,
        subject_key=subject_key,
        risk=risk,
        chat_connector_write=chat_connector_write,
        chat_platform_write=chat_platform_write,
        unattended_external_write=unattended_external_write,
        device_external_write=device_external_write,
    )
    if forced is not None:
        return forced
    if not policy:
        return ToolApprovalRequirement(
            tool_name=normalized_name,
            required=False,
            reason="No project approval policy is configured.",
            matched_rule="no_policy",
            subject_key=subject_key,
            risk=risk,
        )
    return _policy_requirement(
        policy,
        normalized_name,
        subject_key=subject_key,
        risk=risk,
        definition_risk=definition_risk,
        subject_risk=subject_risk,
    )


def _per_call_requirement(
    normalized_name: str,
    policy: dict[str, Any],
    *,
    subject_key: str,
    risk: str,
    chat_connector_write: bool,
    chat_platform_write: bool,
    unattended_external_write: bool,
    device_external_write: bool,
) -> ToolApprovalRequirement | None:
    """The rule that asks a person for this very call, whatever the project policy says; ``None`` when none does."""
    if normalized_name in OUTBOUND_MESSAGE_DEFINITION_NAMES:
        # A message to a person outside the session is approved one by one, whatever the policy says.
        rule = RULE_OUTBOUND_MESSAGE
        reason = "A message to a person outside this session needs a person's approval before it is sent."
    elif chat_connector_write:
        rule = RULE_CHAT_CONNECTOR_WRITE
        reason = "This writes to a connected system from the chat; confirm exactly this call before it runs."
    elif chat_platform_write:
        rule = RULE_CHAT_PLATFORM_WRITE
        reason = "This writes to the platform from the chat; confirm exactly this call before it runs."
    elif unattended_external_write and not (
        {normalized_name, subject_key} & _normalized_names(policy.get("unattended_allowed_tools"))
    ):
        rule = RULE_UNATTENDED_EXTERNAL_WRITE
        reason = ("No person started this run (an event or a schedule did): its write to an external system is a"
                  " proposal a person approves. A platform admin can allow a specific tool for unattended runs.")
    elif device_external_write:
        rule = RULE_DEVICE_EXTERNAL_WRITE
        reason = ("A device asked to write to an external system through Octryx; a person approves this call in "
                  "Octryx before it runs, then the device repeats it.")
    else:
        return None
    return ToolApprovalRequirement(
        tool_name=normalized_name,
        required=True,
        reason=reason,
        matched_rule=rule,
        subject_key=subject_key,
        risk=risk,
    )


def _policy_requirement(
    policy: dict[str, Any],
    normalized_name: str,
    *,
    subject_key: str,
    risk: str,
    definition_risk: str,
    subject_risk: str,
) -> ToolApprovalRequirement:
    exempt_names = _normalized_names(policy.get("exempt_tools"))
    required_names = _normalized_names(policy.get("require_for_tools"))
    required_risks = {name.lower() for name in _normalized_names(policy.get("require_for_risks"))}
    # Each policy identity of this request carries its own risk and is waived
    # only by an exemption naming that identity, so neither the dispatched tool
    # nor the capability subject can waive the other's rule.
    identity_risks = _policy_identity_risks(
        (normalized_name, definition_risk),
        (subject_key, subject_risk),
    )
    governed = {name: risks for name, risks in identity_risks.items() if name not in exempt_names}
    exempted = [name for name in identity_risks if name in exempt_names]

    if governed.keys() & required_names:
        return ToolApprovalRequirement(
            tool_name=normalized_name,
            required=True,
            reason="Project approval policy requires approval for this tool.",
            matched_rule="require_for_tools",
            subject_key=subject_key,
            risk=risk,
        )
    matched_risks = {value for risks in governed.values() for value in risks} & required_risks
    if matched_risks:
        matched_risk = risk if risk in matched_risks else sorted(matched_risks)[0]
        return ToolApprovalRequirement(
            tool_name=normalized_name,
            required=True,
            reason=f"Project approval policy requires approval for '{matched_risk}'-risk tools.",
            matched_rule="require_for_risks",
            subject_key=subject_key,
            risk=matched_risk,
        )
    if exempted:
        return ToolApprovalRequirement(
            tool_name=normalized_name,
            required=False,
            reason="Tool is exempt from central approval enforcement.",
            matched_rule="exempt_tools",
            subject_key=subject_key,
            risk=risk,
        )
    return ToolApprovalRequirement(
        tool_name=normalized_name,
        required=False,
        reason="No approval policy rule matched this tool.",
        matched_rule="no_match",
        subject_key=subject_key,
        risk=risk,
    )
