"""An audit event about something that always lives in a Workspace carries it in ``audit_log.project_id``; one
without it has no known owner and no reader is shown it (fail closed)."""

from __future__ import annotations

from sqlalchemy import or_

from ...models import AuditLog

# Kinds whose resource may also be platform-wide (flows, plugins, connector watchers, named connections, global
# workflows and sync configs, the work items they import and what runs on those) set the column only when the
# resource has a Workspace, so they are not listed; a kind whose resource_id is the Workspace itself resolves
# through ``AuditLog.__workspace_scope__``.
WORKSPACE_RESOURCE_TYPES = frozenset({
    "agent_board_message",
    "agent_presence",
    "check_proposal",
    "code_repository",
    "code_style_repository",
    "code_style_workspace",
    "connection_deviation",
    "documentation_write_intent",
    "knowledge_memory_item",
    "knowledge_source",
    "knowledge_source_connector",
    "secure_work_pull_request",
    "session_lessons",
    "work_item_claim",
    "work_item_handoff_attachment",
    "work_item_takeover",
    "workflow_run",
    "workspace_connection",
    "workspace_content_handling",
})


def owner_known():
    # Spelled positively: a negated IN over a NULL resource type would drop that row too.
    return or_(AuditLog.resource_type.is_(None), AuditLog.resource_type.not_in(WORKSPACE_RESOURCE_TYPES),
               AuditLog.project_id.is_not(None))


__all__ = ["WORKSPACE_RESOURCE_TYPES", "owner_known"]
