from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from tests.alembic_model_parity_support import (
    DIALECTS,
    ScratchDatabase,
    alembic_version,
    assert_exact_residual,
    head_revision,
    schema_drift,
)
from tests.support.alembic_model_parity_residual import expected_residual
from tests.support.alembic_upgrade_support import insert_row, upgraded_database

BEFORE = "a0006runner_runtime"
STARTED = datetime(2026, 1, 1)
WORKSPACE, OTHER, SHARED, NO_WORKSPACE = (str(uuid.uuid4()) for _ in range(4))
USER, REPOSITORY, GONE, RUN = "user-0001", "repository-0001", "repository-0002", "run-0001"
ROWS = {
    "audit-repository": ("code_repository", REPOSITORY, {}),
    "audit-details": ("code_repository", GONE, {"workspace_id": OTHER}),
    "audit-unresolved": ("code_repository", GONE, {"connector_id": "connector-0001"}),
    "audit-path": ("api", "", {"path": f"/api/v1/workspaces/{OTHER}/repositories"}),
    "audit-workspace": ("project", WORKSPACE, {}),
    "audit-platform": ("system_config", "agent.policy", {}),
    "audit-connection": ("workspace_connection", f"{SHARED}:jira", {}),
    "audit-connection-gone": ("workspace_connection", f"{NO_WORKSPACE}:jira", {}),
    "audit-deviation": ("connection_deviation", f"connection-0001:{WORKSPACE}", {}),
    "audit-run-command": ("server_command", RUN, {"command": "ruff check ."}),
}


def _seed(connection: Connection) -> None:
    insert_row(connection, "projects", id=WORKSPACE, name="demo-shop", source_type="local", is_system=False,
               access_mode="private")
    insert_row(connection, "projects", id=SHARED, name="demo-team", source_type="local", is_system=False,
               access_mode="shared")
    insert_row(connection, "users", id=USER, username="demo-owner", email="owner@example.test",
               password_hash="disabled", auth_source="local", account_type="human")
    insert_row(connection, "code_repositories", id=REPOSITORY, project_id=WORKSPACE, name="demo-repo",
               repo_root="/repos/demo", provider="local", index_backend="none", semantic_backend="none",
               structure_backend="none", graph_backend="none")
    insert_row(connection, "workflow_runs", id=RUN, project_id=WORKSPACE, workflow_kind="phased",
               workflow_key="demo-flow", title="", workflow_version="", pull_request={}, status="running",
               node_state={}, loop_counters={}, limits={}, budget_usage={}, gate_results={}, context={},
               requested_by=USER, created_at=STARTED, updated_at=STARTED)
    for row_id, (kind, resource_id, details) in ROWS.items():
        insert_row(connection, "audit_log", id=row_id, user_id=USER, action=f"{kind}.changed", resource_type=kind,
                   resource_id=resource_id, details=details)


def _workspaces(connection: Connection) -> dict[str, str | None]:
    return dict(connection.execute(sa.text("SELECT id, project_id FROM audit_log")).tuples().all())


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-audit-workspace"), _seed,
                           revision=BEFORE) as database:
        yield database


def test_the_upgrade_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_each_existing_row_takes_the_workspace_its_resource_or_record_names(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_workspaces) == {
        "audit-repository": WORKSPACE,
        "audit-details": OTHER,
        "audit-unresolved": None,
        "audit-path": OTHER,
        "audit-workspace": WORKSPACE,
        "audit-platform": None,
        "audit-connection": SHARED,
        "audit-connection-gone": None,
        "audit-deviation": WORKSPACE,
        "audit-run-command": WORKSPACE,
    }


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))
