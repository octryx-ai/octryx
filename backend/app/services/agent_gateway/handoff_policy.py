"""Writing the Workspace handoff policy.

``set_workspace_handoff_policy`` validates the section (``handoff_policy_keys``), checks that the stored policy
merged with it still validates (a broken stored policy is a coded refusal before any write, like the seat
switch), writes ``agent_gateway_policy.handoff`` through the governed project-config path and records an audit
row. A policy that sets only the seat keys and/or the handoff section keeps the baseline (``policy.py``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project
from .handoff_policy_keys import HANDOFF_POLICY_KEY, HandoffPolicy, HandoffPolicyError, normalize_handoff_policy
from .policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from .policy_normalize import normalize_agent_gateway_policy

AUDIT_ACTION = "admin.agent_gateway.handoff_policy_updated"
REASON_POLICY_INVALID = "agent_gateway_policy_invalid"


async def set_workspace_handoff_policy(
    db: AsyncSession, *, project: Project, value: Any, actor_id: str
) -> HandoffPolicy:
    """Store the validated section; raises ``HandoffPolicyError`` (field reasons or the stored-policy reason)."""
    section = normalize_handoff_policy(value, f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{HANDOFF_POLICY_KEY}")
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    if stored is not None:
        candidate = {**stored, HANDOFF_POLICY_KEY: section} if isinstance(stored, dict) else stored
        try:
            normalize_agent_gateway_policy(candidate)
        except AgentGatewayPolicyError as error:
            raise HandoffPolicyError(REASON_POLICY_INVALID, error.path) from None
    before = stored.get(HANDOFF_POLICY_KEY) if isinstance(stored, dict) else None
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    await apply_project_config_patch(
        db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: {HANDOFF_POLICY_KEY: section}},
        actor_user_id=actor_id,
    )
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": section}))
    await db.flush()
    return HandoffPolicy(**section)


__all__ = ["AUDIT_ACTION", "REASON_POLICY_INVALID", "set_workspace_handoff_policy"]
