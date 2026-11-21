"""Workspace policy for governed external coding clients (``agent_gateway_policy``).

Stored in ``projects.config["agent_gateway_policy"]`` and validated on every admin
write (``admin_project_config_service``). Shape::

    {"verification": {"test_command_prefixes": [["pytest"], ["python", "-m", "pytest"]],
                      "change_tools": ["Edit", "Write", "MultiEdit", "NotebookEdit"]},
     "tool_rules": [{"id": "...", "kind": "<rule kind>", ...}],
     "client_permissions": {"deny": ["Bash(git push origin main:*)"], "ask": []},
     "session_budget": {"per_user_daily_usd": 50},
     "sandbox": {"allowed_domains": ["pypi.org", "*.npmjs.org"]},
     "seat_mode": "forbidden", "requires_governed_routing": false, "seat_models": ["claude-sonnet-5"],
     "seat_allows_governed_models": false}

The seat keys are validated in ``seat_policy_keys.py`` and decided in ``seat_policy.py``.

Rule kinds (closed vocabulary; anything else is invalid, never ignored):

- ``command_prefix_denied``     ``prefix``: token list
- ``command_requires_argument`` ``command``: token list, ``argument``: str
- ``command_argument_denied``   ``command``: token list, ``argument``: str
- ``path_denied``               ``tools``: tool names, ``glob``: fnmatch pattern

A Workspace without a policy gets the code-defined ``BASELINE_POLICY`` and says so
(``policy_source="baseline"``); so does a stored policy that only sets the seat keys (the baseline plus
those keys). A stored policy that no longer validates is not
replaced by the baseline: it is ``needs_configuration / policy_invalid``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from .handoff_policy_keys import HANDOFF_POLICY_KEY
from .policy_keys import (
    AGENT_GATEWAY_POLICY_CONFIG_KEY,
    AUTONOMY_ALLOW,
    BASELINE_POLICY,
    POLICY_SOURCE_BASELINE,
    POLICY_SOURCE_WORKSPACE,
    AgentGatewayPolicyError,
)
from .policy_normalize import normalize_agent_gateway_policy
from .review_keys import REVIEW_KEY
from .seat_policy_keys import SEAT_POLICY_KEYS
from .transcript_policy_keys import SESSION_TRANSCRIPTS_KEY


@dataclass(frozen=True, slots=True)
class ToolRule:
    id: str
    kind: str
    tokens: tuple[str, ...] = ()
    argument: str = ""
    tools: frozenset[str] = frozenset()
    glob: str = ""


@dataclass(frozen=True, slots=True)
class VerificationConfig:
    test_command_prefixes: tuple[tuple[str, ...], ...]
    change_tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class GatewayPolicy:
    source: str
    tool_rules: tuple[ToolRule, ...] = ()
    verification: VerificationConfig | None = None
    deny_permissions: tuple[str, ...] = ()
    ask_permissions: tuple[str, ...] = ()
    # The autonomy set (``AUTONOMY_ALLOW`` unless the Workspace set its own list).
    allow_permissions: tuple[str, ...] = AUTONOMY_ALLOW
    # None: no daily budget configured; the model gateway then refuses with needs_configuration.
    daily_budget_usd: Decimal | None = None
    # Domains Bash in Claude Code's sandbox may reach (``sandbox_policy.py``); empty: the user is asked.
    sandbox_allowed_domains: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyLoad:
    """Either a usable policy or the explicit reason there is none."""

    policy: GatewayPolicy | None
    source: str
    reason: str = ""


def _rule(item: dict[str, Any]) -> ToolRule:
    return ToolRule(
        id=item["id"],
        kind=item["kind"],
        tokens=tuple(item.get("prefix") or item.get("command") or ()),
        argument=item.get("argument", ""),
        tools=frozenset(item.get("tools") or ()),
        glob=item.get("glob", ""),
    )


def build_policy(normalized: dict[str, Any], *, source: str) -> GatewayPolicy:
    verification = normalized.get("verification") or {}
    prefixes = tuple(tuple(item) for item in verification.get("test_command_prefixes") or ())
    change_tools = frozenset(verification.get("change_tools") or ())
    permissions = normalized.get("client_permissions") or {}
    budget = (normalized.get("session_budget") or {}).get("per_user_daily_usd")
    return GatewayPolicy(
        source=source,
        tool_rules=tuple(_rule(item) for item in normalized.get("tool_rules") or ()),
        verification=VerificationConfig(prefixes, change_tools) if prefixes and change_tools else None,
        deny_permissions=tuple(permissions.get("deny") or ()),
        ask_permissions=tuple(permissions.get("ask") or ()),
        allow_permissions=tuple(permissions["allow"]) if "allow" in permissions else AUTONOMY_ALLOW,
        daily_budget_usd=Decimal(str(budget)) if budget is not None else None,
        sandbox_allowed_domains=tuple((normalized.get("sandbox") or {}).get("allowed_domains") or ()),
        raw=normalized,
    )


def resolve_policy_from_config(config: Any) -> PolicyLoad:
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    if stored is None or stored == {}:
        return PolicyLoad(build_policy(BASELINE_POLICY, source=POLICY_SOURCE_BASELINE), POLICY_SOURCE_BASELINE)
    try:
        normalized = normalize_agent_gateway_policy(stored)
    except AgentGatewayPolicyError:
        return PolicyLoad(None, POLICY_SOURCE_WORKSPACE, "policy_invalid")
    if set(normalized) <= SEAT_POLICY_KEYS | {HANDOFF_POLICY_KEY, SESSION_TRANSCRIPTS_KEY, REVIEW_KEY}:
        # Only the seat switches, the handoff policy, the transcript switch and/or the reviewer's model are set:
        # the rest stays the baseline, so none drops the baseline tool rules and daily budget.
        baseline = build_policy({**BASELINE_POLICY, **normalized}, source=POLICY_SOURCE_BASELINE)
        return PolicyLoad(baseline, POLICY_SOURCE_BASELINE)
    return PolicyLoad(build_policy(normalized, source=POLICY_SOURCE_WORKSPACE), POLICY_SOURCE_WORKSPACE)


async def load_workspace_policy(db: AsyncSession, project_id: str) -> PolicyLoad:
    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    return resolve_policy_from_config(config)


__all__ = [
    "GatewayPolicy",
    "PolicyLoad",
    "ToolRule",
    "VerificationConfig",
    "build_policy",
    "load_workspace_policy",
    "resolve_policy_from_config",
]
