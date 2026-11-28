"""Standing tool approvals per Workspace: ``project_config["standing_tool_approvals"]``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ...models import Session as AgentSession
from ...time_utils import utc_now_aware
from .argument_class import StandingRuleScope, valid_argument_class, valid_tool_name
from .permission import require_standing_grant_permission

logger = logging.getLogger(__name__)

STANDING_TOOL_APPROVALS_CONFIG_KEY = "standing_tool_approvals"
RULES_FIELD = "rules"
MAX_STANDING_TOOL_RULES = 100
_GRANT_TEXT_MAX_CHARS = 64

ERROR_INVALID_PAYLOAD = "invalid_payload"
ERROR_INVALID_TOOL_NAME = "invalid_tool_name"
ERROR_INVALID_ARGUMENT_CLASS = "invalid_argument_class"
ERROR_TOO_MANY_RULES = "too_many_rules"
STANDING_TOOL_RULE_ERROR_CODES = frozenset(
    {ERROR_INVALID_PAYLOAD, ERROR_INVALID_TOOL_NAME, ERROR_INVALID_ARGUMENT_CLASS, ERROR_TOO_MANY_RULES}
)


class StandingToolApprovalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        if code not in STANDING_TOOL_RULE_ERROR_CODES:
            raise ValueError(f"unknown standing tool approval error code: {code}")
        super().__init__(message)
        self.code = code


def _bounded_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _GRANT_TEXT_MAX_CHARS:
        raise StandingToolApprovalError(ERROR_INVALID_PAYLOAD, "granted_by and granted_at are short strings.")
    return value


def normalize_standing_tool_approvals(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {RULES_FIELD}:
        message = f"{STANDING_TOOL_APPROVALS_CONFIG_KEY} holds only rules."
        raise StandingToolApprovalError(ERROR_INVALID_PAYLOAD, message)
    rules = value.get(RULES_FIELD) or []
    if not isinstance(rules, list):
        raise StandingToolApprovalError(ERROR_INVALID_PAYLOAD, "rules must be a list.")
    by_scope: dict[tuple[str, str | None], dict[str, Any]] = {}
    for entry in rules:
        if not isinstance(entry, dict):
            raise StandingToolApprovalError(ERROR_INVALID_PAYLOAD, "Each rule is an object.")
        tool_name = entry.get("tool_name")
        argument_class = entry.get("argument_class")
        if not valid_tool_name(tool_name):
            raise StandingToolApprovalError(ERROR_INVALID_TOOL_NAME, "A rule names a tool or approval subject.")
        if not valid_argument_class(argument_class):
            raise StandingToolApprovalError(
                ERROR_INVALID_ARGUMENT_CLASS, "An argument class is an executable, optionally with one subcommand."
            )
        by_scope[(tool_name, argument_class)] = {
            "tool_name": tool_name,
            "argument_class": argument_class,
            "granted_by": _bounded_text(entry.get("granted_by")),
            "granted_at": _bounded_text(entry.get("granted_at")),
        }
    if len(by_scope) > MAX_STANDING_TOOL_RULES:
        raise StandingToolApprovalError(
            ERROR_TOO_MANY_RULES, f"A Workspace holds at most {MAX_STANDING_TOOL_RULES} standing tool approvals."
        )
    return {RULES_FIELD: list(by_scope.values())} if by_scope else {}


def standing_tool_rules_in(config: Any) -> frozenset[StandingRuleScope]:
    section = config.get(STANDING_TOOL_APPROVALS_CONFIG_KEY) if isinstance(config, dict) else None
    rules = section.get(RULES_FIELD) if isinstance(section, dict) else None
    return frozenset(
        StandingRuleScope(entry["tool_name"], entry.get("argument_class"))
        for entry in (rules if isinstance(rules, list) else [])
        if isinstance(entry, dict)
        and valid_tool_name(entry.get("tool_name"))
        and valid_argument_class(entry.get("argument_class"))
    )


async def _session_project_config(db: AsyncSession, session_id: str | None) -> tuple[str | None, Any]:
    if not session_id:
        return None, None
    row = (
        await db.execute(
            select(Project.id, Project.config)
            .join(AgentSession, AgentSession.project_id == Project.id)
            .where(AgentSession.id == session_id)
        )
    ).first()
    return (str(row[0]), row[1]) if row is not None else (None, None)


async def standing_rule_covers(db: AsyncSession | None, *, session_id: str | None, scope: StandingRuleScope) -> bool:
    if db is None:
        return False
    project_id, config = await _session_project_config(db, session_id)
    covered = scope in standing_tool_rules_in(config)
    if covered:
        logger.info(
            "tool_approval.standing_rule_applied",
            extra={
                "session_id": session_id,
                "project_id": project_id,
                "tool_name": scope.tool_name,
                "argument_class": scope.argument_class,
            },
        )
    return covered


@dataclass(frozen=True, slots=True)
class StandingRuleCheck:
    scope: StandingRuleScope | None
    covered: bool

    @property
    def scope_payload(self) -> dict[str, Any] | None:
        return self.scope.to_payload() if self.scope is not None else None


async def check_standing_rule(
    db: AsyncSession | None, *, session_id: str | None, scope: StandingRuleScope | None
) -> StandingRuleCheck:
    covered = scope is not None and await standing_rule_covers(db, session_id=session_id, scope=scope)
    return StandingRuleCheck(scope, covered)


async def grant_standing_tool_rule(
    db: AsyncSession, *, project_id: str | None, scope: StandingRuleScope, decider_id: str
) -> None:
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    workspace_id = await require_standing_grant_permission(db, user_id=decider_id, project_id=project_id)
    project = await db.get(Project, workspace_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    config = dict(project.config or {}) if isinstance(project.config, dict) else {}
    section = config.get(STANDING_TOOL_APPROVALS_CONFIG_KEY)
    current = section.get(RULES_FIELD) if isinstance(section, dict) else None
    rules = [
        entry
        for entry in (current if isinstance(current, list) else [])
        if not (
            isinstance(entry, dict)
            and entry.get("tool_name") == scope.tool_name
            and entry.get("argument_class") == scope.argument_class
        )
    ]
    rules.append({**scope.to_payload(), "granted_by": decider_id, "granted_at": utc_now_aware().isoformat()})
    await apply_project_config_patch(
        db,
        project=project,
        patch={STANDING_TOOL_APPROVALS_CONFIG_KEY: {RULES_FIELD: rules}},
        actor_user_id=decider_id,
    )


__all__ = [
    "MAX_STANDING_TOOL_RULES",
    "RULES_FIELD",
    "STANDING_TOOL_APPROVALS_CONFIG_KEY",
    "STANDING_TOOL_RULE_ERROR_CODES",
    "StandingRuleCheck",
    "StandingToolApprovalError",
    "check_standing_rule",
    "grant_standing_tool_rule",
    "normalize_standing_tool_approvals",
    "standing_rule_covers",
    "standing_tool_rules_in",
]
