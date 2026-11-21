"""The one resolution point of sensitive-content handling: per content kind, which action applies where.

**Kinds** (:data:`KINDS`): one per shipped built-in detector except ``prompt_injection`` (fixed, below).
**Actions** a Workspace admin chooses (:data:`ACTIONS`): ``refuse``, ``mask``, ``reroute`` (to the Workspace's
governance alias), ``mask_reroute``, ``report`` (the text goes on unchanged; the finding is recorded as an
informational decision).
``none`` (not acted on) and ``review`` (Command safety asks a person) exist only as shipped defaults.

**Precedence**, the same at every enforcement point: the Workspace's setting for the kind
(``workspace_content_handling``), else the shipped default of the point's surface (:data:`SHIPPED_DEFAULTS`).

**Governance alias**: one governed model alias per Workspace (``workspace_content_governance``), the only target of
every ``reroute`` / ``mask_reroute`` kind (:attr:`HandlingPlan.governance_alias`); a kind may only be set to reroute
while it is set (``handling_settings``).

**Scope**: a point resolves its plan for a Workspace id or for an explicit :class:`PlatformScope` (no Workspace by
design, with one of :data:`PLATFORM_SCOPE_REASONS`; the shipped defaults apply). A point with neither is refused
(:class:`ContentHandlingScopeMissingError`, ``content_handling_scope_missing``): an unset scope is never read as the
shipped defaults. Surfaces:

- ``platform`` — model calls through a provider driver (chat, tasks, governed runs) and tool results: credentials
  masked, email masked, internal IPs reported;
- ``gateway`` — a whole request of an external coding agent (``content_routing.gateway``): only credentials
  (:data:`GATEWAY_KINDS`): ``secrets`` refused by default (``platform:secrets-never-leave``), ``credential_assignment``
  reported by default; a Workspace may set ``refuse`` or ``report`` for either (:data:`GATEWAY_ACTIONS`). Every other
  kind, and ``mask``, ``reroute`` and ``mask_reroute``, apply to platform calls only: on the gateway such a setting
  leaves the kind at its default (``platform_calls_only``);
- ``commands`` — Command safety's ``command_guardrail``: credentials and internal IPs sent for review.

What each configured action does at each enforcement point (:data:`POINT_MODEL_CALL` …), and what the fixed rules do
there, is the point table of ``content_security.handling_points``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkspaceContentGovernance, WorkspaceContentHandling
from ..content_detection.vocabulary import (
    DETECTOR_CREDENTIAL_ASSIGNMENT,
    DETECTOR_EMAIL,
    DETECTOR_IBAN,
    DETECTOR_INTERNAL_IP,
    DETECTOR_PHONE,
    DETECTOR_SECRETS,
)

ACTION_REFUSE = "refuse"
ACTION_MASK = "mask"
ACTION_REROUTE = "reroute"
ACTION_MASK_REROUTE = "mask_reroute"
ACTION_REPORT = "report"
ACTIONS: tuple[str, ...] = (ACTION_REFUSE, ACTION_MASK, ACTION_REROUTE, ACTION_MASK_REROUTE, ACTION_REPORT)
ACTION_NONE = "none"
ACTION_REVIEW = "review"
ACTION_DENY = "deny"
MASKING = frozenset({ACTION_MASK, ACTION_MASK_REROUTE})
REROUTING = frozenset({ACTION_REROUTE, ACTION_MASK_REROUTE})

SURFACE_PLATFORM = "platform"
SURFACE_GATEWAY = "gateway"
SURFACE_COMMANDS = "commands"

POLICY_PROMPT_INJECTION_REFUSED = "platform:prompt-injection-refused"
POLICY_UNSCANNED_WITHHELD = "platform:unscanned-content-withheld"
POLICY_UNREADABLE_REFUSED = "platform:unreadable-content-refused"
POLICY_SECRETS_NEVER_LEAVE = "platform:secrets-never-leave"
REASON_ROUTE_UNAVAILABLE = "content_route_unavailable"
REASON_HANDLING_UNAVAILABLE = "content_handling_unavailable"
REASON_HANDLING_SCOPE_MISSING = "content_handling_scope_missing"
REASON_GATEWAY_REFUSED = "content_handling_gateway_refused"
REASON_REROUTE_MASKED = "reroute_masked"
REASON_DEFERRED_TO_MODEL = "deferred_to_model_entrance"
REASON_COMMAND_REVIEW = "command_review"
REASON_COMMAND_DENIED = "command_denied"
REASON_PLATFORM_ONLY = "platform_calls_only"
REASON_OLDER_HISTORY_MASKED = "older_history_masked"
RECORD_KIND = "content_handling"


@dataclass(frozen=True, slots=True)
class ContentKind:
    kind: str
    label: str
    commands: bool = False


KINDS: tuple[ContentKind, ...] = (
    ContentKind(DETECTOR_SECRETS, "Credentials (keys, tokens, private keys)", commands=True),
    ContentKind(DETECTOR_CREDENTIAL_ASSIGNMENT, "Credential assignments (password = …)", commands=True),
    ContentKind(DETECTOR_EMAIL, "Email addresses"),
    ContentKind(DETECTOR_INTERNAL_IP, "Internal IP addresses", commands=True),
    ContentKind(DETECTOR_IBAN, "IBANs"),
    ContentKind(DETECTOR_PHONE, "Phone numbers"),
)
KIND_IDS: frozenset[str] = frozenset(item.kind for item in KINDS)
COMMAND_KINDS: frozenset[str] = frozenset(item.kind for item in KINDS if item.commands)
#: The kinds the gateway of external coding agents acts on (accidental credential leakage).
GATEWAY_KINDS: frozenset[str] = frozenset({DETECTOR_SECRETS, DETECTOR_CREDENTIAL_ASSIGNMENT})

SHIPPED_DEFAULTS: Mapping[str, Mapping[str, str]] = {
    SURFACE_PLATFORM: {DETECTOR_SECRETS: ACTION_MASK, DETECTOR_CREDENTIAL_ASSIGNMENT: ACTION_MASK,
                       DETECTOR_EMAIL: ACTION_MASK, DETECTOR_INTERNAL_IP: ACTION_REPORT},
    SURFACE_GATEWAY: {DETECTOR_SECRETS: ACTION_REFUSE, DETECTOR_CREDENTIAL_ASSIGNMENT: ACTION_REPORT},
    SURFACE_COMMANDS: {kind: ACTION_REVIEW for kind in COMMAND_KINDS},
}
#: The shipped policy id of a default (what records and notices name); a Workspace setting gets its own id.
_SHIPPED_POLICY: Mapping[tuple[str, str], str] = {
    (DETECTOR_SECRETS, ACTION_MASK): "platform:credentials-masked",
    (DETECTOR_CREDENTIAL_ASSIGNMENT, ACTION_MASK): "platform:credentials-masked",
    (DETECTOR_EMAIL, ACTION_MASK): "platform:email-masked",
    (DETECTOR_INTERNAL_IP, ACTION_REPORT): "platform:internal-ip-reported",
    (DETECTOR_SECRETS, ACTION_REFUSE): POLICY_SECRETS_NEVER_LEAVE,
    (DETECTOR_CREDENTIAL_ASSIGNMENT, ACTION_REPORT): "platform:credential-assignments-reported",
    **{(kind, ACTION_REVIEW): "platform:credentials-masked" for kind in (DETECTOR_SECRETS,
                                                                       DETECTOR_CREDENTIAL_ASSIGNMENT)},
    (DETECTOR_INTERNAL_IP, ACTION_REVIEW): "platform:internal-ip-reported",
}
#: The configurable actions an external coding agent's gateway acts on (forward unchanged or refuse); mask, reroute
#: and mask_reroute apply to the platform's own model calls only.
GATEWAY_ACTIONS: frozenset[str] = frozenset({ACTION_REFUSE, ACTION_REPORT})

#: The enforcement points (their table: ``handling_points.POINTS``).
POINT_MODEL_CALL = "model_call"
POINT_MODEL_CALL_DIRECT = "model_call_direct"
POINT_MODEL_OUTPUT = "model_output"
POINT_TOOL_RESULTS = "tool_results"
POINT_GATEWAY_MESSAGES = "gateway_messages"
POINT_GATEWAY_RESPONSES = "gateway_responses"
POINT_CODEX_SEAT = "codex_seat"
POINT_COMMANDS = "commands"




@dataclass(frozen=True, slots=True)
class KindHandling:
    kind: str
    action: str
    is_default: bool

    @property
    def policy_id(self) -> str:
        shipped = _SHIPPED_POLICY.get((self.kind, self.action)) if self.is_default else None
        return shipped or f"workspace:content-handling:{self.kind}:{self.action}"


@dataclass(frozen=True, slots=True)
class HandlingPlan:
    """The frozen per-call plan of one surface: the action of every kind and the Workspace's governance alias (the
    one target of every ``reroute`` / ``mask_reroute`` kind; ``None``: the Workspace has none)."""

    surface: str
    items: tuple[KindHandling, ...]
    governance_alias: str | None

    def get(self, kind: str) -> KindHandling:
        return next(item for item in self.items if item.kind == kind)

    def action(self, kind: str) -> str:
        return self.get(kind).action

    def kinds(self, *actions: str) -> frozenset[str]:
        return frozenset(item.kind for item in self.items if item.action in actions)

    @property
    def acting(self) -> frozenset[str]:
        """The kinds acted on (examined): every kind whose action is not ``none``."""
        return frozenset(item.kind for item in self.items if item.action != ACTION_NONE)

    def policies(self, detected: Iterable[str], *actions: str) -> tuple[str, ...]:
        """The policy ids of the ``detected`` kinds whose action is one of ``actions`` (in kind order, once)."""
        found = set(detected)
        ids: list[str] = []
        for item in self.items:
            if item.kind in found and item.action in actions and item.policy_id not in ids:
                ids.append(item.policy_id)
        return tuple(ids)

    def record(self, detected: Iterable[str]) -> dict[str, object] | None:
        """What a decision record carries (its ``obligation``): the action applied per detected kind, ``report``
        ones informational; ``None`` when the plan acted on none of them."""
        found = {item.kind for item in self.items if item.kind in set(detected) and item.action != ACTION_NONE}
        return self.record_of(found) if found else None

    def record_of(self, kinds: Iterable[str]) -> dict[str, object]:
        found = [item for item in self.items if item.kind in set(kinds)]
        return {"kind": RECORD_KIND, "surface": self.surface,
                "applied": {item.kind: item.action for item in found},
                "informational": [item.kind for item in found if item.action == ACTION_REPORT],
                "workspace_setting": [item.kind for item in found if not item.is_default]}


Settings = Mapping[str, str]


def _applies(surface: str, info: ContentKind, action: str) -> bool:
    """Whether a Workspace's ``action`` for ``info`` applies on ``surface`` (the gateway: :data:`GATEWAY_KINDS` with
    :data:`GATEWAY_ACTIONS` only; Command safety: its kinds only)."""
    if surface == SURFACE_GATEWAY:
        return info.kind in GATEWAY_KINDS and action in GATEWAY_ACTIONS
    return surface != SURFACE_COMMANDS or info.commands


def plan_for(settings: Settings, surface: str, governance_alias: str | None = None) -> HandlingPlan:
    """The plan of ``surface`` from a Workspace's ``settings`` (kind → action) over the shipped defaults, with its
    ``governance_alias``; a setting that does not apply on the surface leaves the kind at its default there."""
    defaults = SHIPPED_DEFAULTS[surface]
    items = []
    for info in KINDS:
        if info.kind in settings and _applies(surface, info, settings[info.kind]):
            items.append(KindHandling(info.kind, settings[info.kind], False))
        else:
            items.append(KindHandling(info.kind, defaults.get(info.kind, ACTION_NONE), True))
    return HandlingPlan(surface, tuple(items), governance_alias)


def shipped_plan(surface: str) -> HandlingPlan:
    return plan_for({}, surface)


class ContentHandlingUnavailableError(RuntimeError):
    """The Workspace's settings could not be read: the call is refused, never decided on assumed defaults."""


class ContentHandlingScopeMissingError(RuntimeError):
    """A plan was asked for neither a Workspace nor an explicit :class:`PlatformScope`: refused, never decided on
    assumed defaults."""


#: Why a point has no Workspace by design: a chat session (or its turn's tool context) without one, a stored record
#: whose Workspace column is empty (Work Item, workflow run, CallAgent configuration), a knowledge retrieval without a
#: Workspace filter.
PLATFORM_SESSION_WITHOUT_WORKSPACE = "session_without_workspace"
PLATFORM_RECORD_WITHOUT_WORKSPACE = "record_without_workspace"
PLATFORM_RETRIEVAL_WITHOUT_WORKSPACE = "retrieval_without_workspace"
PLATFORM_SCOPE_REASONS = frozenset({PLATFORM_SESSION_WITHOUT_WORKSPACE, PLATFORM_RECORD_WITHOUT_WORKSPACE,
                                    PLATFORM_RETRIEVAL_WITHOUT_WORKSPACE})


@dataclass(frozen=True, slots=True)
class PlatformScope:
    """A point with no Workspace by design (``reason``: one of :data:`PLATFORM_SCOPE_REASONS`): shipped defaults."""

    reason: str

    def __post_init__(self) -> None:
        if self.reason not in PLATFORM_SCOPE_REASONS:
            raise ValueError(f"unknown platform scope reason: {self.reason!r}")


HandlingScope = str | PlatformScope


async def workspace_settings(db: AsyncSession, workspace_id: str | None) -> dict[str, str]:
    """The Workspace's stored action per kind (kind → action)."""
    if not workspace_id:
        return {}
    rows = (await db.execute(select(WorkspaceContentHandling).where(
        WorkspaceContentHandling.workspace_id == workspace_id))).scalars()
    return {row.kind: row.action for row in rows if row.kind in KIND_IDS and row.action in ACTIONS}


async def governance_alias(db: AsyncSession, workspace_id: str | None) -> str | None:
    """The Workspace's governance alias (``None``: none set)."""
    if not workspace_id:
        return None
    return (await db.execute(select(WorkspaceContentGovernance.governance_alias).where(
        WorkspaceContentGovernance.workspace_id == workspace_id))).scalar_one_or_none()


async def content_handling(db: AsyncSession, workspace_id: str | None, surface: str) -> HandlingPlan:
    """The plan of ``surface`` for ``workspace_id`` (shipped defaults and no governance alias without a Workspace)."""
    return plan_for(await workspace_settings(db, workspace_id), surface, await governance_alias(db, workspace_id))


async def content_handling_isolated(scope: HandlingScope, surface: str) -> HandlingPlan:
    """:func:`content_handling` in its own session, for a point without one (the provider wrapper, tool results):
    the Workspace's plan, or the shipped defaults for an explicit :class:`PlatformScope`. A scope that is
    neither raises :class:`ContentHandlingScopeMissingError`; a failed read raises
    :class:`ContentHandlingUnavailableError`."""
    if isinstance(scope, PlatformScope):
        return shipped_plan(surface)
    if not isinstance(scope, str) or not scope.strip():
        raise ContentHandlingScopeMissingError(surface)
    workspace_id = scope
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as session:
            return await content_handling(session, workspace_id, surface)
    except Exception as exc:  # noqa: BLE001 - an unread setting refuses; it is never replaced by a default
        raise ContentHandlingUnavailableError(workspace_id) from exc


__all__ = [
    "ACTIONS",
    "ACTION_DENY",
    "ACTION_MASK",
    "ACTION_MASK_REROUTE",
    "ACTION_NONE",
    "ACTION_REFUSE",
    "ACTION_REPORT",
    "ACTION_REROUTE",
    "ACTION_REVIEW",
    "COMMAND_KINDS",
    "GATEWAY_ACTIONS",
    "GATEWAY_KINDS",
    "KINDS",
    "KIND_IDS",
    "MASKING",
    "POINT_CODEX_SEAT",
    "POINT_COMMANDS",
    "POINT_GATEWAY_MESSAGES",
    "POINT_GATEWAY_RESPONSES",
    "POINT_MODEL_CALL",
    "POINT_MODEL_CALL_DIRECT",
    "POINT_MODEL_OUTPUT",
    "POINT_TOOL_RESULTS",
    "POLICY_PROMPT_INJECTION_REFUSED",
    "POLICY_SECRETS_NEVER_LEAVE",
    "POLICY_UNREADABLE_REFUSED",
    "POLICY_UNSCANNED_WITHHELD",
    "PLATFORM_RECORD_WITHOUT_WORKSPACE",
    "PLATFORM_RETRIEVAL_WITHOUT_WORKSPACE",
    "PLATFORM_SCOPE_REASONS",
    "PLATFORM_SESSION_WITHOUT_WORKSPACE",
    "REASON_COMMAND_DENIED",
    "REASON_COMMAND_REVIEW",
    "REASON_DEFERRED_TO_MODEL",
    "REASON_GATEWAY_REFUSED",
    "REASON_HANDLING_SCOPE_MISSING",
    "REASON_REROUTE_MASKED",
    "REASON_HANDLING_UNAVAILABLE",
    "REASON_OLDER_HISTORY_MASKED",
    "REASON_PLATFORM_ONLY",
    "REASON_ROUTE_UNAVAILABLE",
    "REROUTING",
    "SHIPPED_DEFAULTS",
    "SURFACE_COMMANDS",
    "SURFACE_GATEWAY",
    "SURFACE_PLATFORM",
    "ContentHandlingScopeMissingError",
    "ContentHandlingUnavailableError",
    "ContentKind",
    "HandlingPlan",
    "HandlingScope",
    "KindHandling",
    "PlatformScope",
    "content_handling",
    "content_handling_isolated",
    "governance_alias",
    "plan_for",
    "shipped_plan",
    "workspace_settings",
]
