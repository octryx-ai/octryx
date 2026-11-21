"""Whether a Workspace allows the ``seat`` profile.

Five keys of ``agent_gateway_policy`` (validated with the rest of the policy on every admin write):

- ``seat_mode``: ``allowed`` or ``forbidden``; when absent, :func:`default_seat_mode` decides by the Workspace's
  classification (allowed for public and internal, forbidden from confidential up);
- ``requires_governed_routing``: ``true`` forbids seat mode whatever ``seat_mode`` says;
- ``seat_models``: the Anthropic model ids a seat session may call (default
  :data:`BASELINE_SEAT_MODELS`: derived from the model data, so
  every default model, the reviewer's included, is admitted: ``seat_models.json`` ``seat_baseline_also``);
- ``seat_allows_governed_models``: a seat session may also pick the Workspace's company models,
  which then run through the governed path (default false);
- ``codex_seat_mode``: ``allowed`` or ``forbidden`` (when absent: the same default as ``seat_mode``): the Codex
  seat (a person's own ChatGPT login, ``model_gateway/inbound/codex_seat``) under the same classification and
  governed-routing rules.

The Workspace data classification overrides the policy through the classification policy matrix
(``data_classification/policy_matrix``): a level whose ``seat_allowed`` is false (default: from
``confidential`` up) or whose ``requires_governed_routing`` is true forbids seat mode, and so does an
unresolved classification (fail closed: "not confidential" cannot be shown). Every refusal is a fixed
code; there is no silent fallback to the governed route.
"""

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
    """The decision from the Workspace policy and the matrix alone (also the policy test bench's comparison).

    ``codex``: the Codex seat (a person's own ChatGPT login): the same classification and governed-routing rules,
    its own switch ``codex_seat_mode``; its models are ``codex_seat_models`` when set (empty: every Codex model, Codex
    picks its own) and never company models.
    """
    raw = policy.raw or {}
    if level_rules is None:
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
    """The decision for one Workspace policy and the matrix rules of its level (``None``: unresolved).

    The classification is evaluated first: a Workspace the classification forbids reports that
    reason whatever its switches say, so the settings disable the seat toggle up front. The Cedar policy
    engine evaluates the same question (``level`` names the level of ``level_rules``): in shadow mode its
    answer never changes this decision; in enforce mode a Cedar denial of an allowed seat is
    ``cedar_policy_denied``.
    """
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
    if enforced_denial(decision.allowed, comparison) is not None:
        return SeatDecision(False, REASON_CEDAR_POLICY_DENIED)
    return decision


async def workspace_seat_decision(
    db: AsyncSession, workspace_id: str, *, principal: Any = None, codex: bool = False
) -> SeatDecision:
    """``principal``: the requesting user and seat session (``request_principal.load_seat_principal``);
    ``None`` for a Workspace-level view, which no user's who-condition narrows. ``codex``: the Codex seat's
    decision (``codex_seat_mode``) instead of the Claude seat's (``seat_mode``)."""
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
