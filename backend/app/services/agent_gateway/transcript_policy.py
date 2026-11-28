"""Writing the Workspace switch "full session transcripts", audited like the handoff policy."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Project
from .policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from .policy_normalize import normalize_agent_gateway_policy
from .transcript_policy_keys import (
    SESSION_TRANSCRIPTS_KEY,
    TranscriptPolicy,
    TranscriptPolicyError,
    normalize_transcript_policy,
)

AUDIT_ACTION = "admin.agent_gateway.session_transcripts_updated"
REASON_POLICY_INVALID = "agent_gateway_policy_invalid"


async def set_workspace_transcript_policy(
    db: AsyncSession, *, project: Project, value: Any, actor_id: str
) -> TranscriptPolicy:
    section = normalize_transcript_policy(value, f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{SESSION_TRANSCRIPTS_KEY}")
    config = project.config if isinstance(project.config, dict) else {}
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    if stored is not None:
        candidate = {**stored, SESSION_TRANSCRIPTS_KEY: section} if isinstance(stored, dict) else stored
        try:
            normalize_agent_gateway_policy(candidate)
        except AgentGatewayPolicyError as error:
            raise TranscriptPolicyError(REASON_POLICY_INVALID, error.path) from None
    before = stored.get(SESSION_TRANSCRIPTS_KEY) if isinstance(stored, dict) else None
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    await apply_project_config_patch(
        db, project=project, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: {SESSION_TRANSCRIPTS_KEY: section}},
        actor_user_id=actor_id,
    )
    db.add(AuditLog(user_id=actor_id, action=AUDIT_ACTION, resource_type="workspace", resource_id=project.id,
                    details={"before": before, "after": section}))
    await db.flush()
    return TranscriptPolicy(**section)


__all__ = ["AUDIT_ACTION", "REASON_POLICY_INVALID", "set_workspace_transcript_policy"]
