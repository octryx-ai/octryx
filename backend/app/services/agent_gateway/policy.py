"""Workspace policy for governed external coding clients (``agent_gateway_policy``): baseline and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from .policy_keys import (
    AGENT_GATEWAY_POLICY_CONFIG_KEY,
    AUTONOMY_ALLOW,
    BASELINE_DAILY_BUDGET_USD,
    BASELINE_POLICY,
    POLICY_SOURCE_BASELINE,
    POLICY_SOURCE_WORKSPACE,
    RULE_KEYS,
    AgentGatewayPolicyError,
    over_baseline,
)
from .policy_normalize import normalize_agent_gateway_policy


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
    # A Workspace without its own daily budget has the platform's (the baseline).
    daily_budget_usd: Decimal = Decimal(BASELINE_DAILY_BUDGET_USD)
    # Domains Bash in Claude Code's sandbox may reach (``sandbox_policy.py``); empty: the user is asked.
    sandbox_allowed_domains: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyLoad:
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
    budget = (normalized.get("session_budget") or {}).get("per_user_daily_usd", BASELINE_DAILY_BUDGET_USD)
    return GatewayPolicy(
        source=source,
        tool_rules=tuple(_rule(item) for item in normalized.get("tool_rules") or ()),
        verification=VerificationConfig(prefixes, change_tools) if prefixes and change_tools else None,
        deny_permissions=tuple(permissions.get("deny") or ()),
        ask_permissions=tuple(permissions.get("ask") or ()),
        allow_permissions=tuple(permissions["allow"]) if "allow" in permissions else AUTONOMY_ALLOW,
        daily_budget_usd=Decimal(str(budget)),
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
    source = POLICY_SOURCE_WORKSPACE if set(normalized) & RULE_KEYS else POLICY_SOURCE_BASELINE
    return PolicyLoad(build_policy(over_baseline(normalized), source=source), source)


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
