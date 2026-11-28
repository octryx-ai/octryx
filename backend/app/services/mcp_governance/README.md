# MCP governance

Identity, catalog mirror, policy and audit of the MCP tools, resources and prompts mirrored into a Workspace.
Whether a project may reach an MCP server at all is `services/mcp_access_policy.py`.

## Invariants

- A resource mirror run creates every binding disabled (`resource_catalog_write.py`, `resource_lifecycle.py`).
- A resource or prompt that is not mirrored into the Workspace catalog is denied (`resource_policy.decide_mcp_resource`).
- Without a database session, a resolved Workspace or a user, a resource or prompt request is denied
  (`resource_gate.decide_mcp_resource_for_context`).
- A governance audit row never holds the governed URI (`resource_decision.McpResourceDecision.audit_metadata`).
- An admin binding update with a risk outside the closed list is refused (`capability_admin_policy.py`,
  `resource_admin_policy.py`).
