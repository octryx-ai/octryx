"""The platform approval rule: does a governed change need a second admin?

Stored in ``system_config`` under :data:`APPROVAL_RULE_CONFIG_KEY`; edited by platform admins in
Settings → Governance → "Approval rule". Two values:

* ``four_eyes`` — the default (also for a missing or unreadable value): an admin other than the
  author approves before anyone can publish;
* ``single_admin`` — for an installation with one admin: the author approves their own change and
  publishes it in one step; every such publish is audited as ``approval_mode: self``.

The decision itself lives in ``services.governance.four_eyes``; this module only stores, reads and
audits the rule.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, SystemConfig
from ..system_config.values import set_system_config_value

APPROVAL_RULE_CONFIG_KEY = "governance.approval_rule"
APPROVAL_RULE_FOUR_EYES = "four_eyes"
APPROVAL_RULE_SINGLE_ADMIN = "single_admin"
APPROVAL_RULES = (APPROVAL_RULE_FOUR_EYES, APPROVAL_RULE_SINGLE_ADMIN)
DEFAULT_APPROVAL_RULE = APPROVAL_RULE_FOUR_EYES
APPROVAL_RULE_LABELS = {
    APPROVAL_RULE_FOUR_EYES: "Four-eyes (a second admin approves)",
    APPROVAL_RULE_SINGLE_ADMIN: "Single admin may approve own changes",
}

AUDIT_APPROVAL_RULE_UPDATED = "governance.approval_rule_updated"
ERROR_APPROVAL_RULE_INVALID = "approval_rule_invalid"


class ApprovalRuleError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_approval_rule(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in APPROVAL_RULES else DEFAULT_APPROVAL_RULE


async def load_approval_rule(db: AsyncSession) -> str:
    row = await db.get(SystemConfig, APPROVAL_RULE_CONFIG_KEY)
    return parse_approval_rule(row.value if row is not None else None)


async def set_approval_rule(db: AsyncSession, *, rule: Any, actor_id: str) -> str:
    """Store the rule and audit the change (who, old → new); flushes, the caller commits."""
    value = str(rule or "").strip().lower()
    if value not in APPROVAL_RULES:
        raise ApprovalRuleError(ERROR_APPROVAL_RULE_INVALID)
    previous = await load_approval_rule(db)
    if value == previous:
        return value
    await set_system_config_value(db, key=APPROVAL_RULE_CONFIG_KEY, value=value, description="Platform approval rule",
                                  updated_by=actor_id, record_prompt_revision=False)
    db.add(AuditLog(user_id=actor_id, action=AUDIT_APPROVAL_RULE_UPDATED, resource_type="system_config",
                    resource_id=APPROVAL_RULE_CONFIG_KEY, details={"previous": previous, "rule": value}))
    await db.flush()
    return value


async def approval_rule_status(db: AsyncSession) -> dict[str, Any]:
    """What the UI shows: the stored rule, whether self-approval is in effect, and why."""
    from .four_eyes import self_approval_source

    row = await db.get(SystemConfig, APPROVAL_RULE_CONFIG_KEY)
    rule = parse_approval_rule(row.value if row is not None else None)
    source = await self_approval_source(db)
    return {
        "rule": rule,
        "label": APPROVAL_RULE_LABELS[rule],
        "options": [{"value": value, "label": APPROVAL_RULE_LABELS[value]} for value in APPROVAL_RULES],
        "self_approval_allowed": source is not None,
        "self_approval_source": source,
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


__all__ = [
    "APPROVAL_RULES",
    "APPROVAL_RULE_CONFIG_KEY",
    "APPROVAL_RULE_FOUR_EYES",
    "APPROVAL_RULE_SINGLE_ADMIN",
    "AUDIT_APPROVAL_RULE_UPDATED",
    "ApprovalRuleError",
    "approval_rule_status",
    "load_approval_rule",
    "set_approval_rule",
]
