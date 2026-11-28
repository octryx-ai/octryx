"""Whether a Workspace allows the ``seat`` profile, for the Claude and the Codex seat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_classification.policy_rules import LevelRules

from ..data_classification.workspace_overrides import workspace_rules_by_id
from ..model_gateway.data_policy.source import resolve_workspace_data_classification
from ..policy_engine.points import POINT_SEAT, seat_query
from ..policy_engine.runtime import maintain_policy_runtime
from ..policy_engine.shadow import REASON_CEDAR_POLICY_DENIED, LegacyDecision, enforced_denial, shadow_decision
from .policy import GatewayPolicy, load_workspace_policy
from .seat_policy_keys import (
    BASELINE_SEAT_MODELS,
    CODEX_SEAT_MODE_KEY,
    CODEX_SEAT_MODELS_KEY,
    REASON_CODEX_SEAT_MODE_FORBIDDEN,
    REASON_SEAT_CLASSIFICATION,
    REASON_SEAT_CLASSIFICATION_REQUIRES_GOVERNED,
    REASON_SEAT_CLASSIFICATION_UNRESOLVED,
    REASON_SEAT_MODE_FORBIDDEN,
    REASON_SEAT_POLICY_INVALID,
    REASON_SEAT_REQUIRES_GOVERNED,
    REQUIRES_GOVERNED_KEY,
    SEAT_ALLOWS_GOVERNED_MODELS_KEY,
    SEAT_MODE_ALLOWED,
    SEAT_MODE_FORBIDDEN,
    SEAT_MODE_KEY,
    SEAT_MODELS_KEY,
)


@dataclass(frozen=True, slots=True)
class SeatDecision:
    allowed: bool
    reason: str = ""
    models: tuple[str, ...] = ()
    # Company models are offered to (and accepted from) this seat session. Only ever true when allowed.
    governed_models: bool = False

    @property
    def seat_mode(self) -> str:
        return SEAT_MODE_ALLOWED if self.allowed else SEAT_MODE_FORBIDDEN


# Allow by default: a Workspace that never set its seat switch may use the seat when it holds public
# or internal data; from confidential up the seat stays off until an admin allows it. A stored switch always wins.
SEAT_OPEN_LEVELS = frozenset({"public", "internal"})


def default_seat_mode(level: str | None) -> str:
    return SEAT_MODE_ALLOWED if str(level or "") in SEAT_OPEN_LEVELS else SEAT_MODE_FORBIDDEN


def builtin_seat_decision(policy: GatewayPolicy, level_rules: LevelRules | None, *, codex: bool = False,
                         level: str | None = None) -> SeatDecision:
    raw = policy.raw or {}
    if level_rules is None:
        # Fail closed: an unresolved classification cannot show that the data is not confidential.
        return SeatDecision(False, REASON_SEAT_CLASSIFICATION_UNRESOLVED)
    if not level_rules.seat_allowed:
        return SeatDecision(False, REASON_SEAT_CLASSIFICATION)
    if level_rules.requires_governed_routing:
        return SeatDecision(False, REASON_SEAT_CLASSIFICATION_REQUIRES_GOVERNED)
    if raw.get(REQUIRES_GOVERNED_KEY) is True:
        return SeatDecision(False, REASON_SEAT_REQUIRES_GOVERNED)
    if codex:
        if raw.get(CODEX_SEAT_MODE_KEY, default_seat_mode(level)) != SEAT_MODE_ALLOWED:
            return SeatDecision(False, REASON_CODEX_SEAT_MODE_FORBIDDEN)
        return SeatDecision(True, models=tuple(raw.get(CODEX_SEAT_MODELS_KEY) or ()))
    if raw.get(SEAT_MODE_KEY, default_seat_mode(level)) != SEAT_MODE_ALLOWED:
        return SeatDecision(False, REASON_SEAT_MODE_FORBIDDEN)
    return SeatDecision(True, models=tuple(raw.get(SEAT_MODELS_KEY) or BASELINE_SEAT_MODELS),
                        governed_models=raw.get(SEAT_ALLOWS_GOVERNED_MODELS_KEY) is True)


def seat_decision_for(
    policy: GatewayPolicy,
    level_rules: LevelRules | None,
    *,
    workspace_id: str | None = None,
    level: str | None = None,
    user_id: str | None = None,
    principal: Any = None,
    codex: bool = False,
) -> SeatDecision:
    decision = builtin_seat_decision(policy, level_rules, codex=codex, level=level)
    raw = dict(policy.raw or {})
    if codex:  # Cedar asks the same seat question, with the Codex switch in the place of ``seat_mode``
        raw[SEAT_MODE_KEY] = raw.get(CODEX_SEAT_MODE_KEY, default_seat_mode(level))
    else:
        raw[SEAT_MODE_KEY] = raw.get(SEAT_MODE_KEY, default_seat_mode(level))
    comparison = shadow_decision(
        POINT_SEAT,
        LegacyDecision(decision.allowed, decision.reason),
        lambda: seat_query(workspace_id=workspace_id, level=level, rules=level_rules, raw_policy=raw,
                           user_id=user_id, principal=principal),
    )
    # In shadow mode Cedar never changes the decision; in enforce mode its denial does.
    if enforced_denial(decision.allowed, comparison) is not None:
        return SeatDecision(False, REASON_CEDAR_POLICY_DENIED)
    return decision


async def workspace_seat_decision(
    db: AsyncSession, workspace_id: str, *, principal: Any = None, codex: bool = False
) -> SeatDecision:
    loaded = await load_workspace_policy(db, workspace_id)
    if loaded.policy is None:
        return SeatDecision(False, loaded.reason or REASON_SEAT_POLICY_INVALID)
    classification = await resolve_workspace_data_classification(db, project_id=workspace_id)
    await maintain_policy_runtime()
    if not classification.resolved:
        return seat_decision_for(loaded.policy, None, workspace_id=workspace_id, principal=principal, codex=codex)
    level = classification.classification
    rules = await workspace_rules_by_id(db, workspace_id, level)  # with the Workspace's stricter overrides
    return seat_decision_for(loaded.policy, rules, workspace_id=workspace_id, level=level, principal=principal,
                             codex=codex)


__all__ = ["SeatDecision", "builtin_seat_decision", "seat_decision_for", "workspace_seat_decision"]
