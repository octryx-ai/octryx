"""Which audit rows are administrative changes, and their category (O5).

The audit log also holds operational events (connector runs, flow steps, MCP knowledge reads, seeding, bootstrap
writes, generic rows of ordinary API calls). Observability → Audit log lists administrative changes only: a row
belongs to the first category whose action pattern it matches; a row that matches none (or an exclusion) is not
an administrative change and is not listed. Patterns are SQL ``LIKE`` patterns over ``audit_log.action``; generic
middleware rows have the form ``METHOD /path`` and are matched by their path.
"""

from __future__ import annotations

from sqlalchemy import String, and_, case, cast, not_, or_

from ...models import AuditLog

ACCESS = "Access & identity"
GOVERNANCE = "Governance"
RUNTIME = "Runtime & models"
CONNECTIONS = "Connections & secrets"
DATA = "Data"
CATEGORIES = (ACCESS, GOVERNANCE, RUNTIME, CONNECTIONS, DATA)

PATTERNS: dict[str, tuple[str, ...]] = {
    ACCESS: ("auth.%", "device.%", "admin.user%", "admin.role%", "admin.group%", "admin.identity%",
             "admin.api_key%", "admin.access%", "% %/users%", "% %/roles%", "% %/groups%", "% %/identity%"),
    GOVERNANCE: ("governance.%", "policy_engine.%", "policy_list.%", "model_policy.%", "workflow_routing_policy.%",
                 "skill_catalog.%", "prompt_catalog.%", "agent_definition.%",
                 "flow_draft_saved%", "flow.publish%", "admin.exec_policy%", "admin.classification%",
                 "admin.approval%", "% %/policies%", "% %/governance%", "% %/policy-engine%"),
    # ``admin.agent_gateway.%``: coding engine (platform default, Workspace engines) and the Workspace switches of the
    # agent gateway; ``user.agent_engine%``: a person's own engine choice.
    RUNTIME: ("runtime.%", "admin.provider%", "admin.runtime%", "admin.system_config%", "tool_config.%",
              "admin.agent_gateway.%", "user.agent_engine%",
              "% %/providers%", "% %/runtime%", "% /admin/tools/configs%"),
    CONNECTIONS: ("knowledge.connector.configure%", "knowledge.connector.delete%", "knowledge.workspace.%",
                  "mcp.server%", "admin.connector%", "admin.secret%", "admin.mcp%", "admin.webhook%", "admin.channel%",
                  "code_repository.%", "% %/connectors%", "% %/secrets%", "% %/mcp/servers%", "% %/webhooks%",
                  "% %/channels%"),
    DATA: ("project.%", "admin.project%", "observability.%", "backup.%", "retention.%", "privacy.%",
           "% %/backup%", "% %/exports%", "% %/projects%"),
}
# Operational noise inside otherwise matching families.
EXCLUDED = ("%.seed", "% %/knowledge/search%", "% %/knowledge/changes%", "% /api/v1/sessions%")
BOOTSTRAP_MARKER = '%"writer_class": "bootstrap"%'


def category_expression():
    excluded = or_(*(AuditLog.action.like(pattern) for pattern in EXCLUDED),
                   cast(AuditLog.details, String).like(BOOTSTRAP_MARKER))
    return case(
        *((and_(not_(excluded), or_(*(AuditLog.action.like(pattern) for pattern in patterns))), category)
          for category, patterns in PATTERNS.items()),
        else_=None,
    )


__all__ = ["CATEGORIES", "category_expression"]
