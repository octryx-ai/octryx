"""The Workspace handoff policy, ``agent_gateway_policy.handoff``.

``{mode: "confirm" | "auto", auto_threshold_pct, require_spare_pct, allowed_requesters: "members" |
"admins_and_owners", push: "branch" | "bundle_only" | "off", auto_trigger_pct}`` (``push`` and
``auto_trigger_pct``: how the client's WIP branch travels and when it hands over by itself).

``confirm`` (the default): a person confirms every takeover in the UI. ``auto`` lets
the server confirm a takeover itself when every condition of ``agent_board/auto_takeover.py`` holds.

Missing fields take their defaults; anything else that is not exactly one of the allowed values is refused with
a fixed reason and path (``AgentGatewayPolicyError`` in ``policy.py``). A Workspace whose stored policy cannot be
read gets the default, so an unreadable policy never hands anything over by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

HANDOFF_POLICY_KEY = "handoff"
MODE_CONFIRM = "confirm"
MODE_AUTO = "auto"
MODES = frozenset({MODE_CONFIRM, MODE_AUTO})
REQUESTERS_MEMBERS = "members"
REQUESTERS_ADMINS = "admins_and_owners"
REQUESTERS = frozenset({REQUESTERS_MEMBERS, REQUESTERS_ADMINS})
PUSH_BRANCH = "branch"
PUSH_BUNDLE_ONLY = "bundle_only"
PUSH_OFF = "off"
PUSH_MODES = frozenset({PUSH_BRANCH, PUSH_BUNDLE_ONLY, PUSH_OFF})
_FIELDS = frozenset({
    "mode", "auto_threshold_pct", "require_spare_pct", "allowed_requesters", "push", "auto_trigger_pct",
    "offer_timeout_minutes",
})


class HandoffPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


@dataclass(frozen=True, slots=True)
class HandoffPolicy:
    mode: str = MODE_CONFIRM
    auto_threshold_pct: float = 90.0
    require_spare_pct: float = 50.0
    allowed_requesters: str = REQUESTERS_MEMBERS
    # Freeze 3c: how the client's WIP branch travels, and the use at which the client hands over by itself.
    push: str = PUSH_BRANCH
    auto_trigger_pct: float = 99.0
    # How long an offer waits for the offered agent's request before it moves to the next candidate.
    offer_timeout_minutes: float = 10.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_HANDOFF_POLICY = HandoffPolicy()


def _pct(value: Any, path: str, *, low: float, high: float) -> float:
    if type(value) not in (int, float) or not low <= value <= high:
        raise HandoffPolicyError("invalid_percentage", path)
    return float(value)


def _minutes(value: Any, path: str) -> float:
    if type(value) not in (int, float) or not 1 <= value <= 1440:
        raise HandoffPolicyError("invalid_minutes", path)
    return float(value)


def _push(value: Any, path: str) -> str:
    if value not in PUSH_MODES:
        raise HandoffPolicyError("invalid_push_mode", path)
    return value


def normalize_handoff_policy(value: Any, path: str) -> dict[str, Any]:
    """The validated section for storage, all fields filled; raises ``HandoffPolicyError``."""
    if not isinstance(value, dict):
        raise HandoffPolicyError("not_an_object", path)
    unknown = sorted(set(value) - _FIELDS)
    if unknown:
        raise HandoffPolicyError("unknown_field", f"{path}.{unknown[0]}")
    mode = value.get("mode", DEFAULT_HANDOFF_POLICY.mode)
    if mode not in MODES:
        raise HandoffPolicyError("invalid_handoff_mode", f"{path}.mode")
    requesters = value.get("allowed_requesters", DEFAULT_HANDOFF_POLICY.allowed_requesters)
    if requesters not in REQUESTERS:
        raise HandoffPolicyError("invalid_allowed_requesters", f"{path}.allowed_requesters")
    return HandoffPolicy(
        mode=mode,
        auto_threshold_pct=_pct(value.get("auto_threshold_pct", DEFAULT_HANDOFF_POLICY.auto_threshold_pct),
                                f"{path}.auto_threshold_pct", low=1, high=100),
        require_spare_pct=_pct(value.get("require_spare_pct", DEFAULT_HANDOFF_POLICY.require_spare_pct),
                               f"{path}.require_spare_pct", low=0, high=99),
        allowed_requesters=requesters,
        push=_push(value.get("push", DEFAULT_HANDOFF_POLICY.push), f"{path}.push"),
        auto_trigger_pct=_pct(value.get("auto_trigger_pct", DEFAULT_HANDOFF_POLICY.auto_trigger_pct),
                              f"{path}.auto_trigger_pct", low=1, high=100),
        offer_timeout_minutes=_minutes(value.get("offer_timeout_minutes",
                                                 DEFAULT_HANDOFF_POLICY.offer_timeout_minutes),
                                       f"{path}.offer_timeout_minutes"),
    ).as_dict()


def handoff_policy_from_config(config: Any) -> tuple[HandoffPolicy, str]:
    """``(policy, source)``: the Workspace's stored section (``workspace``) or the default (``default``)."""
    stored = config.get("agent_gateway_policy") if isinstance(config, dict) else None
    section = stored.get(HANDOFF_POLICY_KEY) if isinstance(stored, dict) else None
    if section is None:
        return DEFAULT_HANDOFF_POLICY, "default"
    try:
        return HandoffPolicy(**normalize_handoff_policy(section, HANDOFF_POLICY_KEY)), "workspace"
    except HandoffPolicyError:
        return DEFAULT_HANDOFF_POLICY, "default"


__all__ = [
    "DEFAULT_HANDOFF_POLICY",
    "HANDOFF_POLICY_KEY",
    "MODE_AUTO",
    "MODE_CONFIRM",
    "PUSH_BRANCH",
    "PUSH_BUNDLE_ONLY",
    "PUSH_OFF",
    "REQUESTERS_ADMINS",
    "REQUESTERS_MEMBERS",
    "HandoffPolicy",
    "HandoffPolicyError",
    "handoff_policy_from_config",
    "normalize_handoff_policy",
]
