"""The effective policy of one Workspace in one read-only view (``GET .../policy-summary``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY
from app.services.agent_gateway.seat_settings import seat_mode_set, stored_seat_mode

from ...models import Project
from ..agent_gateway.policy import load_workspace_policy
from ..agent_gateway.seat_policy import workspace_seat_decision
from ..agent_gateway.seat_policy_keys import CODEX_SEAT_MODE_KEY
from ..budget.agent_cost_limits import (
    SOURCE_DEFAULT,
    SOURCE_WORKSPACE,
    agent_request_cost_limit,
    agent_session_cost_limit,
)
from ..knowledge.projection.workspace_classification_default import workspace_classification_view
from ..model_gateway.data_policy.classification import DATA_POLICY_CONFIG_KEY, resolve_data_classification
from ..model_gateway.data_policy.effects import gateway_aliases
from ..model_gateway.litellm.project_admission import build_project_model_admission
from ..named_connections.summary import workspace_connection_summary
from .policy_matrix import load_classification_policy
from .workspace_overrides import apply_overrides, stored_overrides

SUMMARY_ADMISSION_SOURCE = "workspace_policy_summary"
SOURCE_UNSET = "unset"


def _rule_target(rule: Any) -> dict[str, Any]:
    if rule.glob:
        return {"tools": sorted(rule.tools), "glob": rule.glob}
    target: dict[str, Any] = {"command": list(rule.tokens)}
    if rule.argument:
        target["argument"] = rule.argument
    return target


def _gateway_policy(loaded: Any) -> dict[str, Any]:
    policy = loaded.policy
    if policy is None:
        return {"state": "needs_configuration", "reason": loaded.reason or "policy_invalid", "source": loaded.source,
                "tool_rules": [], "client_permissions": {"deny": [], "ask": []}}
    return {
        "state": "ok",
        "reason": None,
        "source": policy.source,
        "tool_rules": [{"id": rule.id, "kind": rule.kind, "target": _rule_target(rule)} for rule in policy.tool_rules],
        "client_permissions": {"deny": list(policy.deny_permissions), "ask": list(policy.ask_permissions)},
    }


def _daily_budget(project: Project, loaded: Any) -> dict[str, Any]:
    policy = loaded.policy
    if policy is None:
        return {"value_usd": None, "source": SOURCE_UNSET}
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    # A budget the Workspace policy does not set itself is the baseline's (inherited): the built-in default.
    own = isinstance(stored, dict) and "session_budget" in stored
    return {"value_usd": float(policy.daily_budget_usd), "source": SOURCE_WORKSPACE if own else SOURCE_DEFAULT}


async def _models(db: AsyncSession, project: Project, allowlists: dict[str, frozenset[str]]) -> dict[str, Any]:
    config = project.config if isinstance(project.config, dict) else {}
    admission = build_project_model_admission(
        project_id=project.id,
        project_config=config,
        source=SUMMARY_ADMISSION_SOURCE,
        data_classification=resolve_data_classification(project_data_policy=config.get(DATA_POLICY_CONFIG_KEY)),
        level_model_aliases=allowlists,
    )
    allowed: list[str] = []
    denied: list[dict[str, str]] = []
    for alias, allowance in await gateway_aliases(db):
        decision = admission.decide(alias)
        reason = decision.reason
        if decision.allowed:
            data_decision = admission.decide_data_policy(allowance)
            if data_decision.allowed:
                allowed.append(alias)
                continue
            reason = data_decision.reason
        denied.append({"alias": alias, "reason": reason})
    return {"allowed_aliases": allowed, "denied": denied}


def _limit(limit: Any) -> dict[str, Any]:
    return {"value_usd": float(limit.value), "source": limit.source}


async def workspace_policy_summary(db: AsyncSession, project: Project) -> dict[str, Any]:
    view = await workspace_classification_view(db, project.id)
    matrix = await load_classification_policy(db)
    level = view["effective"]
    rules = apply_overrides(matrix.rules_for(level), stored_overrides(project.config)).to_dict() if level else None
    loaded = await load_workspace_policy(db, project.id)
    seat = await workspace_seat_decision(db, project.id)
    return {
        "project_id": project.id,
        "classification": {"effective": level, "source": view["source"]},
        "matrix_state": matrix.state,
        "rules": rules,
        "seat": {"seat_mode": stored_seat_mode(project.config), "in_effect": seat.allowed,
                 "reason": seat.reason or None, "seat_mode_set": seat_mode_set(project.config),
                 "codex_seat_mode_set": seat_mode_set(project.config, CODEX_SEAT_MODE_KEY)},
        "agent_gateway_policy": _gateway_policy(loaded),
        "models": await _models(db, project, matrix.model_allowlists()),
        "budgets": {
            "per_user_daily_usd": _daily_budget(project, loaded),
            "session_cost_limit_usd": _limit(await agent_session_cost_limit(db, project_id=project.id)),
            "request_cost_limit_usd": _limit(await agent_request_cost_limit(db, project_id=project.id)),
        },
        "connectors": rules["connectors"] if rules else None,
        # The connection ids a Cedar policy can name (``context.connections``), per connector.
        "connections": await workspace_connection_summary(db, project.id),
        # The published custom policies that apply here, as sentences.
        "platform_policies": await _platform_policies(db, project.id, level),
    }


async def _platform_policies(db: AsyncSession, project_id: str, level: str | None) -> dict[str, Any]:
    from ..policy_engine.policy_links import workspace_platform_policies

    return await workspace_platform_policies(db, project_id, level)


__all__ = ["workspace_policy_summary"]
