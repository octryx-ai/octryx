"""The policy step of the device dispatch gate."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserDevice
from ..agent_gateway.policy import load_workspace_policy
from ..data_classification.workspace_overrides import workspace_rules_by_id
from ..model_gateway.data_policy.source import resolve_workspace_data_classification
from ..policy_engine.points import POINT_DEVICE_DISPATCH
from ..policy_engine.runtime import maintain_policy_runtime
from ..policy_engine.shadow import REASON_CEDAR_POLICY_DENIED, LegacyDecision, enforced_denial, shadow_decision
from .contract import DEVICE_POLICY_CLIENT, STATE_DENIED, STATE_NEEDS_CONFIGURATION
from .device_runs_keys import device_runs_section
from .platform_switch import device_runs_platform_enabled

REASON_PLATFORM_DISABLED = "device_runs_platform_disabled"
REASON_POLICY_INVALID = "policy_invalid"
REASON_DISABLED = "device_runs_disabled"
REASON_CLASSIFICATION = "device_runs_classification"
REASON_PROFILE_NOT_ALLOWED = "device_profile_not_allowed"
REASON_FOLDER = "folder_not_allowlisted"
REASON_CONTENT_REQUIRES_GOVERNED = "content_requires_governed"
# ``device_runs.sensitive_content_requires_governed`` (bool, default off): the team's opt-in for the check above.
SENSITIVE_CONTENT_REQUIRES_GOVERNED_KEY = "sensitive_content_requires_governed"
_STATES = {REASON_DISABLED: STATE_NEEDS_CONFIGURATION}


def builtin_device_decision(section: dict, rules, *, profile: str, folder_allowlisted: bool) -> LegacyDecision:
    if section.get("enabled") is not True:
        return LegacyDecision(False, REASON_DISABLED)
    if rules is not None and not rules.device_runs_allowed:
        return LegacyDecision(False, REASON_CLASSIFICATION)
    if profile not in section.get("allowed_profiles", []):
        return LegacyDecision(False, REASON_PROFILE_NOT_ALLOWED)
    if not folder_allowlisted:
        return LegacyDecision(False, REASON_FOLDER)
    return LegacyDecision(True)


async def _codex_engine(db: AsyncSession, user_id: str, workspace_id: str | None) -> bool:
    from ..agent_gateway.engine_keys import ENGINE_CODEX
    from ..agent_gateway.engine_policy import effective_engine

    return (await effective_engine(db, user_id=user_id, workspace_id=workspace_id)).engine == ENGINE_CODEX


async def device_run_decision(db: AsyncSession, *, user_id: str, device: UserDevice, workspace_id: str | None,
                              profile: str, folder_allowlisted: bool, session_id: str | None = None):
    from ..policy_engine.device_point import device_query
    from ..policy_engine.principals import load_principal
    from .dispatch_gate import DispatchDecision

    if not await device_runs_platform_enabled(db):
        return DispatchDecision.deny(STATE_DENIED, REASON_PLATFORM_DISABLED)
    if not workspace_id:
        return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_DISABLED)
    loaded = await load_workspace_policy(db, workspace_id)
    if loaded.policy is None:
        return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_POLICY_INVALID)
    section = device_runs_section(loaded.policy.raw)
    classification = await resolve_workspace_data_classification(db, project_id=workspace_id)
    level = classification.classification if classification.resolved else None
    rules = await workspace_rules_by_id(db, workspace_id, level) if level else None  # with stricter overrides
    legacy = builtin_device_decision(section, rules, profile=profile, folder_allowlisted=folder_allowlisted)
    await maintain_policy_runtime()
    principal = await load_principal(db, user_id)
    comparison = shadow_decision(POINT_DEVICE_DISPATCH, legacy, lambda: device_query(
        workspace_id=workspace_id, classification=classification, rules=rules, raw_policy=loaded.policy.raw,
        device=device, profile=profile, folder_allowlisted=folder_allowlisted, principal=principal))
    decision_id = comparison.record_id if comparison is not None else None
    if not legacy.allowed:
        return DispatchDecision.deny(_STATES.get(legacy.reason, STATE_DENIED), legacy.reason, decision_id)
    if (denial := enforced_denial(True, comparison)) is not None:
        return DispatchDecision.deny(STATE_DENIED, REASON_CEDAR_POLICY_DENIED, denial.decision_id)
    if profile == "seat":
        from ..agent_gateway.seat_policy import workspace_seat_decision
        from ..content_routing.conversation_state import CHAT_CONVERSATION, load_state
        from ..policy_engine.request_principal import load_seat_principal

        # A team option, off by default (defaults must let the work run; teams add security). When the
        # Workspace switched it on, a thread that already holds sensitive categories needs the governed profile.
        if section.get(SENSITIVE_CONTENT_REQUIRES_GOVERNED_KEY) is True \
                and (await load_state(session_id, CHAT_CONVERSATION)).categories:
            return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_CONTENT_REQUIRES_GOVERNED, decision_id)
        seat = await workspace_seat_decision(db, workspace_id, codex=await _codex_engine(db, user_id, workspace_id),
                                             principal=await load_seat_principal(
            user_id, session_id=f"device:{device.id}", client=DEVICE_POLICY_CLIENT))
        if not seat.allowed:
            return DispatchDecision.deny(STATE_DENIED, seat.reason, decision_id)
    return DispatchDecision(True, policy_decision_id=decision_id)


__all__ = ["device_run_decision", "builtin_device_decision"]
