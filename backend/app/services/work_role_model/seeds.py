"""The seed functions and roles.

The baseline seeds exactly these rows (``test_work_role_model`` keeps both equal). A ``role:<key>`` decider or
handoff owner names one of the seed role keys (``WORK_ROLE_KEYS``) and resolves through the Workspace's
assignments of that role. Admins change the functions of every seed role and add their own roles; a seed can be
edited but not deleted.

Defaults let people work (too much security blocks the system): every role reads, a Developer
writes through connectors, the Product owner also decides as product owner.
"""
from __future__ import annotations

from typing import NamedTuple


class SeedFunction(NamedTuple):
    key: str
    name: str
    description: str
    tools: tuple[str, ...]


class SeedRole(NamedTuple):
    key: str
    name: str
    description: str
    functions: tuple[str, ...]


READ, WORK_ITEMS, DELIVERY, STEER_RUNS = "read", "work_items", "delivery", "steer_runs"
APPROVE_TOOLS, DECIDE_AS_PO = "approve_tools", "decide_as_po"
WORKSPACE_SETTINGS, ASSIGN_ROLES, GLOBAL_SETTINGS = "workspace_settings", "assign_roles", "global_settings"

SEED_FUNCTIONS: tuple[SeedFunction, ...] = (
    SeedFunction(READ, "Chat & knowledge", "Every read tool, the chat's tool search, personal memory and knowledge "
                 "feedback, and the client's own session bookkeeping.",
                 ("risk:read", "tool_search", "memory_remember", "knowledge_feedback", "session_ingest",
                  "episode_summary", "approval_request")),
    SeedFunction(WORK_ITEMS, "Work items", "Create, note, move, claim and hand over work items; the agent board.",
                 ("work_item_*", "board_*")),
    SeedFunction(DELIVERY, "Delivery", "Connector writes: Jira, Confluence, issues, pull requests and branches, "
                 "through the connections the role is granted.", ("connector:*:write",)),
    SeedFunction(STEER_RUNS, "Start runs", "Start, continue and steer workflow runs and coding agents.",
                 ("workflow_*", "start_workflow", "select_workflow", "coding_agent_start", "work_item_analyze",
                  "work_item_analysis_submit")),
    SeedFunction(APPROVE_TOOLS, "Approve tools", "Answer the tool approvals of runs.", ("approval_*",)),
    SeedFunction(DECIDE_AS_PO, "Decide as product owner", "Answer readiness, interview, review and ship "
                 "decisions of workflow runs. The product-owner gate checks this function, never a role name.",
                 ("change_plan_decide", "workflow_decide")),
    SeedFunction(WORKSPACE_SETTINGS, "Workspace settings", "Change this Workspace's settings.", ()),
    SeedFunction(ASSIGN_ROLES, "Assign roles", "Assign roles in this Workspace and turn role-based tools on or off.",
                 ()),
    SeedFunction(GLOBAL_SETTINGS, "Global settings", "Platform administration tools.", ("risk:admin",)),
)

_DEVELOPER = (READ, WORK_ITEMS, DELIVERY, STEER_RUNS, APPROVE_TOOLS)

SEED_ROLES: tuple[SeedRole, ...] = (
    SeedRole("viewer", "Viewer", "Reads and chats; changes nothing.", (READ,)),
    SeedRole("engineer", "Developer", "Builds: work items, connector writes, runs.", _DEVELOPER),
    SeedRole("product_manager", "Product owner", "Developer rights plus the product owner's decisions.",
             (*_DEVELOPER, DECIDE_AS_PO)),
    SeedRole("workspace_admin", "Workspace admin", "Everything in the Workspace, including roles and settings.",
             (*_DEVELOPER, DECIDE_AS_PO, WORKSPACE_SETTINGS, ASSIGN_ROLES)),
    SeedRole("sre", "SRE", "Operations: work items, connector writes, runs.", _DEVELOPER),
    SeedRole("incident_lead", "Incident lead", "Leads incidents: work items, connector writes, runs.", _DEVELOPER),
    SeedRole("support_agent", "Support agent", "Reads and works on work items.", (READ, WORK_ITEMS)),
    SeedRole("agile_lead", "Agile lead", "Work items and runs.", (READ, WORK_ITEMS, STEER_RUNS)),
    SeedRole("doc_owner", "Documentation owner", "Work items and documentation writes.",
             (READ, WORK_ITEMS, DELIVERY)),
)

#: The role keys a ``role:<key>`` decider or handoff owner may name.
WORK_ROLE_KEYS: frozenset[str] = frozenset(role.key for role in SEED_ROLES)

#: A built-in role that keeps the platform manageable cannot lose these functions (board 8).
PROTECTED_FUNCTIONS: dict[str, frozenset[str]] = {"workspace_admin": frozenset({ASSIGN_ROLES, WORKSPACE_SETTINGS})}



async def ensure_seed_catalog(db) -> None:
    """Insert the seed functions and roles that are missing (a ``create_all`` database: tests, local dev).

    Alembic databases get them from the baseline migration; existing rows are never changed here."""
    from sqlalchemy import select

    from ...models.runtime.work_role_model import WorkRole, WorkRoleFunction, WorkRoleFunctionLink

    functions = {row.key: row for row in (await db.execute(select(WorkRoleFunction).where(
        WorkRoleFunction.project_id.is_(None)))).scalars().all()}
    for seed in SEED_FUNCTIONS:
        if seed.key not in functions:
            functions[seed.key] = WorkRoleFunction(key=seed.key, name=seed.name, description=seed.description,
                                                   built_in=True, tools_json=list(seed.tools))
            db.add(functions[seed.key])
    roles = {row.key for row in (await db.execute(select(WorkRole).where(WorkRole.project_id.is_(None)))
                                 ).scalars().all()}
    await db.flush()
    for seed in SEED_ROLES:
        if seed.key in roles:
            continue
        role = WorkRole(key=seed.key, name=seed.name, description=seed.description, built_in=True,
                        command_policy_json={"allow": [], "deny": []}, connection_ids_json=[])
        db.add(role)
        await db.flush()
        for key in seed.functions:
            db.add(WorkRoleFunctionLink(role_id=role.id, function_id=functions[key].id))
    await db.flush()


__all__ = ["ASSIGN_ROLES", "DECIDE_AS_PO", "PROTECTED_FUNCTIONS", "READ", "SEED_FUNCTIONS", "SEED_ROLES",
           "SeedFunction", "SeedRole", "WORK_ROLE_KEYS", "ensure_seed_catalog"]
