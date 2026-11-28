from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

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
    scratch_database,
)
from tests.support.alembic_model_parity_residual import expected_residual
from tests.support.alembic_upgrade_support import BASELINE_REVISION, insert_row, table_names, upgraded_database

DROPPED_TABLES = {
    "quota_usage_forecasts",
    "secret_scope_bindings",
    "data_classification_policies",
    "data_classification_tags",
    "data_redaction_logs",
    "paused_entities",
    "agent_trace_runs",
    "agent_trace_spans",
    "agent_trace_alert_rules",
}
NOW = dt.datetime(2026, 11, 1, 12, 0)
OLD_TRACE_KNOBS = {"compact_max_string": 800, "compact_max_list_items": 8, "compact_max_dict_items": 24,
                   "always_full_on_error": True, "always_full_on_sensitive_tools": True}
USER, SECRET, POLICY, RUN = "user-0001", "secret-0001", "budget-0001", "trace-run-0001"


def _seed_0_0_1(connection: Connection) -> None:
    insert_row(connection, "users", id=USER, username="upgrade-user", email="upgrade@example.invalid",
               password_hash="synthetic", auth_source="local", account_type="human")
    insert_row(connection, "stored_secrets", id=SECRET, name="synthetic-secret", secret_type="api_key")
    insert_row(connection, "budget_policies", id=POLICY, name="synthetic-budget", reset_period="daily",
               warn_at_percent=80, block_at_percent=100, is_active=True)
    insert_row(connection, "quota_usage_forecasts", id="forecast-0001", policy_id=POLICY, period_key="2026-11-01",
               forecasted_tokens=10, actual_tokens=5, forecasted_cost=Decimal("0.1"), actual_cost=Decimal("0.05"))
    insert_row(connection, "secret_scope_bindings", id="binding-0001", secret_id=SECRET, entity_type="agent",
               entity_id="agent-0001", entity_label="synthetic", permission="read_only", is_active=True,
               created_by=USER, created_at=NOW)
    insert_row(connection, "secret_access_audit_log", id="secret-audit-0001", secret_id=SECRET, action="read",
               outcome="success", created_at=NOW)
    insert_row(connection, "data_classification_policies", id="dcp-0001", entity_type="session",
               default_classification="internal", export_action="allow", auto_redact_pii=False,
               require_export_audit=False, is_active=True)
    insert_row(connection, "data_classification_tags", id="dct-0001", entity_type="session", entity_id="session-0001",
               classification="internal", pii_detected=False, pii_types=[], redaction_applied=False,
               redaction_config={}, sensitivity_tags=[])
    insert_row(connection, "data_redaction_logs", id="drl-0001", entity_type="session", entity_id="session-0001",
               redaction_reason="export", classification="internal", pii_types_redacted=[], redacted_fields=[],
               context_json={})
    insert_row(connection, "paused_entities", id="paused-0001", entity_type="flow", entity_id="flow-0001")
    insert_row(connection, "agent_trace_runs", id=RUN, trace_id="trace-0001", run_kind="chat", status="success",
               started_at=NOW, input_tokens=1, output_tokens=1, total_tokens=2, cost=Decimal("0"),
               created_at=NOW, updated_at=NOW)
    insert_row(connection, "agent_trace_spans", id="span-0001", trace_run_id=RUN, trace_id="trace-0001",
               span_id="span-0001", span_type="llm", name="synthetic", status="success", started_at=NOW,
               input_tokens=1, output_tokens=1, cost=Decimal("0"), created_at=NOW)
    insert_row(connection, "agent_trace_alert_rules", id="alert-0001", name="synthetic", severity="warning",
               enabled=1, created_at=NOW, updated_at=NOW)
    insert_row(connection, "retention_policies", id="retention-0001", entity_type="agent_trace_runs", ttl_days=30,
               action="delete", is_active=True)
    insert_row(connection, "retention_policies", id="retention-0002", entity_type="audit_log", ttl_days=30,
               action="delete", is_active=True)
    insert_row(connection, "projects", id="workspace-0001", name="demo-shop", source_type="local", is_system=False,
               access_mode="private", config={"trace_capture": {"mode": "minimal", **OLD_TRACE_KNOBS}, "theme": "dark"})
    insert_row(connection, "projects", id="workspace-0002", name="demo-blank", source_type="local", is_system=False,
               access_mode="private", config=None)


def _retention_entities(connection: Connection) -> set[str]:
    rows = connection.execute(sa.text("SELECT id, entity_type FROM retention_policies WHERE id LIKE 'retention-%'"))
    return {entity_type for _id, entity_type in rows}


def _secret_audit_ids(connection: Connection) -> list[str]:
    return list(connection.execute(sa.text("SELECT id FROM secret_access_audit_log")).scalars())


def _workspace_configs(connection: Connection) -> dict[str, object]:
    projects = sa.table("projects", sa.column("id", sa.String()), sa.column("config", sa.JSON()))
    rows = connection.execute(sa.select(projects.c.id, projects.c.config).where(projects.c.id.like("workspace-%")))
    return dict(rows.all())


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-0.0.1"), _seed_0_0_1) as database:
        yield database


def test_the_upgrade_from_0_0_1_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_the_upgrade_drops_the_unwired_tables_with_their_rows(upgraded: ScratchDatabase) -> None:
    assert DROPPED_TABLES & upgraded.run(table_names) == set()


def test_the_upgrade_drops_only_the_retention_policy_of_the_dropped_trace_runs(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_retention_entities) == {"audit_log"}


def test_the_upgrade_keeps_the_secret_access_audit_log(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_secret_audit_ids) == ["secret-audit-0001"]


def test_the_upgrade_strips_the_dead_trace_capture_keys(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(_workspace_configs) == {
        "workspace-0001": {"trace_capture": {"mode": "minimal"}, "theme": "dark"},
        "workspace-0002": None,
    }


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_restores_the_empty_tables(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=BASELINE_REVISION, down=True)
        assert DROPPED_TABLES <= database.run(table_names)
