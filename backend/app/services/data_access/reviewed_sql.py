"""SQL the read filter cannot see into: text SQL, reads through a Connection and lightweight ``table()`` clauses. Each
module is reviewed for what it reads; ``tests/guards/test_data_viewer.py`` keeps these lists exact."""

from __future__ import annotations

TEXT_SQL_MODULES: dict[str, str] = {
    "app/db/core.py": "schema introspection at init_db (sqlite_master, pg_indexes, information_schema)",
    "app/db/sqlite.py": "SQLite pragmas and WAL checkpoints",
    "app/db/startup.py": "the startup advisory lock",
    "app/runtime_setup.py": "resets circuit_breaker_states, a platform table without a Workspace",
    "app/services/agent_gateway/sessions.py": "an advisory lock",
    "app/services/database_tool/execution.py": "an admin-defined query against a customer's external database",
    "app/services/database_tool_service.py": "SELECT 1 against a customer's external database",
    "app/services/model_gateway/bundled_litellm.py":
        "whether the bundled LiteLLM's own database exists, in the server's maintenance database, at migrate",
    "app/services/knowledge/evidence_index/postgres_client.py":
        "the Postgres evidence index, outside the ORM; every statement is bound to the project_id its caller "
        "authorized through the filtered ORM",
    "app/services/knowledge/ledger/advisory_locks.py": "an advisory lock",
    "app/services/knowledge/ledger/database_clock.py": "the database clock",
    "app/services/knowledge/temporal/postgres_extraction.py":
        "kg_edge of the temporal graph, outside the ORM, bound to the project_id being extracted",
    "app/services/knowledge/temporal/postgres_extraction_graph.py":
        "kg_node and kg_edge of the temporal graph, outside the ORM, bound to the project_id being extracted",
    "app/services/knowledge/temporal/postgres_graph.py":
        "kg_node and kg_edge reads, outside the ORM, bound to the project_id its caller authorized",
    "app/services/observability/health_checks.py": "SELECT 1 reachability probes",
    "app/services/plugins/image.py": "an advisory lock",
    "app/services/secret/access.py": "whether the caller's transaction has written (its transaction id), no table",
}

CONNECTION_READ_MODULES: dict[str, str] = {
    "app/db/core.py": "schema creation at init_db",
    "app/db/sqlite.py": "SQLite pragmas and WAL checkpoints",
    "app/db/startup.py": "the startup advisory lock",
    "app/models/project/private_guard.py": "a Workspace's access mode, to refuse Work rows in a private Workspace",
    "app/models/session/session.py": "a session's owner, as a user message's author when none is named, at insert",
    "app/models/runtime/catalog_key.py": "a model's provider name and the catalog keys taken, at insert",
    "app/services/data_access/machine_principal.py":
        "an integration's owner and Workspace, before its credential is checked; never returned",
    "app/services/data_access/read_filter.py": "the viewer's hidden Workspaces and granted sessions",
    "app/services/model_gateway/bundled_litellm.py":
        "whether the bundled LiteLLM's own database exists, in the server's maintenance database, at migrate",
    "app/services/database_tool/execution.py": "an admin-defined query against a customer's external database",
    "app/services/database_tool_service.py": "SELECT 1 against a customer's external database",
    "app/services/decisions/approvals.py":
        "the decision timeline record of an approval, written in its flush: the requester's name and the session's "
        "Workspace, both stored on the record only",
    "app/services/devices/runner_queue.py":
        "the oldest chat turns waiting for any server runner (id, owner, Workspace) and their compare-and-set claim; "
        "an idle runner reads as nobody, and each claimed turn is admitted as its owner",
    "app/services/devices/runner_tenant.py":
        "the owner and Workspace of one server runner's active or open jobs, keyed to that verified device; the "
        "runner's account is a member of nothing, so its channel, gateway and admission name the turn's owner",
    "app/services/observability/health_checks.py":
        "SELECT 1 reachability probes, and whether any connector of any Workspace is in error (a yes or no)",
    "app/services/secret/access.py":
        "whether the caller's transaction has written, and the access audit row written in that transaction",
    "app/services/secret/release.py":
        "which tables still hold a secret before it is released; returns table names, never rows",
}

TABLE_CLAUSE_MODULES: dict[str, str] = {
    "app/services/project/private_workspace.py":
        "whether a Workspace or a session's Workspace is private and whose, for checks that refuse other people's",
}


def module_path(module: str) -> str:
    return module.replace(".", "/") + ".py"


__all__ = ["CONNECTION_READ_MODULES", "TABLE_CLAUSE_MODULES", "TEXT_SQL_MODULES", "module_path"]
