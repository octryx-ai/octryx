"""Drop the tables of the removed flow graph runtime (WP-C4b2): orchestrator runs, flow node runs and the never
used flow registry, and the two session columns a flow node turn filled."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0014flow_tables"
down_revision: str | None = "a0013loop_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_flow_node_runs_completed_at"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_created_at"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_flow_version"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_node"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_node_type"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_orchestrator"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_started_at"), table_name="flow_node_runs")
    op.drop_index(op.f("ix_flow_node_runs_status"), table_name="flow_node_runs")
    op.drop_table("flow_node_runs")
    op.drop_index(op.f("ix_flow_registry_versions_created_at"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_created_by"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_deprecated_by"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_entry_id"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_entry_status"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_eval_suite_id"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_flow_definition_version_id"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_published"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_published_at"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_published_by"), table_name="flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_versions_status"), table_name="flow_registry_versions")
    op.drop_table("flow_registry_versions")
    op.drop_index(op.f("ix_flow_registry_entries_created_at"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_created_by"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_current_version_id"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_is_active"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_key"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_project_active"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_project_id"), table_name="flow_registry_entries")
    op.drop_index(op.f("ix_flow_registry_entries_updated_at"), table_name="flow_registry_entries")
    op.drop_table("flow_registry_entries")
    op.drop_index(op.f("ix_sessions_flow_definition_version_id"), table_name="sessions")
    op.drop_column("sessions", "flow_definition_version_id")
    op.drop_column("sessions", "flow_node_id")
    op.drop_index(op.f("ix_orchestrator_agent_runs_completed_at"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_agent_runs_created_at"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_agent_runs_pattern_type"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_agent_runs_project_id"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_agent_runs_status"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_runs_created_at"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_runs_parent_session"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_runs_pattern"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_runs_session_id"), table_name="orchestrator_agent_runs")
    op.drop_index(op.f("ix_orchestrator_runs_status"), table_name="orchestrator_agent_runs")
    op.drop_table("orchestrator_agent_runs")


def downgrade() -> None:
    op.create_table(
        "orchestrator_agent_runs",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("parent_session_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("project_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("pattern_type", sa.VARCHAR(length=32), nullable=False),
        sa.Column("agent_definition_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("flow_definition_version_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("flow_node_id", sa.VARCHAR(length=128), nullable=True),
        sa.Column("current_step_index", sa.INTEGER(), nullable=False),
        sa.Column("total_steps", sa.INTEGER(), nullable=False),
        sa.Column("child_session_ids_json", sa.JSON(), nullable=False),
        sa.Column("merged_output_json", sa.JSON(), nullable=False),
        sa.Column("conflict_resolutions_json", sa.JSON(), nullable=False),
        sa.Column("reviewer_session_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("last_review_score", sa.VARCHAR(length=16), nullable=True),
        sa.Column("last_review_notes", sa.TEXT(), nullable=True),
        sa.Column("revision_count", sa.INTEGER(), nullable=False),
        sa.Column("max_iterations", sa.INTEGER(), nullable=False),
        sa.Column("routing_policy_json", sa.JSON(), nullable=False),
        sa.Column("delegation_policy_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), nullable=False),
        sa.Column("last_child_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("last_error", sa.TEXT(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"],
            ["agent_definitions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["flow_definition_version_id"],
            ["flow_definition_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_session_id"],
            ["sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orchestrator_runs_status"), "orchestrator_agent_runs", ["status"], unique=False)
    op.create_index(op.f("ix_orchestrator_runs_session_id"), "orchestrator_agent_runs", ["session_id"], unique=False)
    op.create_index(op.f("ix_orchestrator_runs_pattern"), "orchestrator_agent_runs", ["pattern_type"], unique=False)
    op.create_index(
        op.f("ix_orchestrator_runs_parent_session"), "orchestrator_agent_runs", ["parent_session_id"], unique=False
    )
    op.create_index(op.f("ix_orchestrator_runs_created_at"), "orchestrator_agent_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_orchestrator_agent_runs_status"), "orchestrator_agent_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_orchestrator_agent_runs_project_id"), "orchestrator_agent_runs", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_orchestrator_agent_runs_pattern_type"), "orchestrator_agent_runs", ["pattern_type"], unique=False
    )
    op.create_index(
        op.f("ix_orchestrator_agent_runs_created_at"), "orchestrator_agent_runs", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_orchestrator_agent_runs_completed_at"), "orchestrator_agent_runs", ["completed_at"], unique=False
    )
    op.add_column("sessions", sa.Column("flow_node_id", sa.VARCHAR(length=128), nullable=True))
    op.add_column("sessions", sa.Column("flow_definition_version_id", sa.VARCHAR(length=36), nullable=True))
    op.create_index(
        op.f("ix_sessions_flow_definition_version_id"), "sessions", ["flow_definition_version_id"], unique=False
    )
    op.create_table(
        "flow_registry_entries",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("key", sa.VARCHAR(length=180), nullable=False),
        sa.Column("name", sa.VARCHAR(length=220), nullable=False),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column("project_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("current_version_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("is_active", sa.BOOLEAN(), nullable=False),
        sa.Column("created_by", sa.VARCHAR(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "project_id", name=op.f("uq_flow_registry_entries_key_project")),
    )
    op.create_index(op.f("ix_flow_registry_entries_updated_at"), "flow_registry_entries", ["updated_at"], unique=False)
    op.create_index(op.f("ix_flow_registry_entries_project_id"), "flow_registry_entries", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_flow_registry_entries_project_active"),
        "flow_registry_entries",
        ["project_id", "is_active"],
        unique=False,
    )
    op.create_index(op.f("ix_flow_registry_entries_key"), "flow_registry_entries", ["key"], unique=False)
    op.create_index(op.f("ix_flow_registry_entries_is_active"), "flow_registry_entries", ["is_active"], unique=False)
    op.create_index(
        op.f("ix_flow_registry_entries_current_version_id"),
        "flow_registry_entries",
        ["current_version_id"],
        unique=False,
    )
    op.create_index(op.f("ix_flow_registry_entries_created_by"), "flow_registry_entries", ["created_by"], unique=False)
    op.create_index(op.f("ix_flow_registry_entries_created_at"), "flow_registry_entries", ["created_at"], unique=False)
    op.create_table(
        "flow_registry_versions",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("entry_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("version", sa.INTEGER(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=30), nullable=False),
        sa.Column("flow_definition_version_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("eval_suite_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("eval_gate_status", sa.VARCHAR(length=20), nullable=False),
        sa.Column("target_project_platforms", sa.JSON(), nullable=False),
        sa.Column("dependency_policy", sa.JSON(), nullable=False),
        sa.Column("runtime_compatibility", sa.JSON(), nullable=False),
        sa.Column("publish_metadata", sa.JSON(), nullable=False),
        sa.Column("impact_summary", sa.JSON(), nullable=False),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("rolled_back_from_version", sa.INTEGER(), nullable=True),
        sa.Column("created_by", sa.VARCHAR(length=36), nullable=False),
        sa.Column("published_by", sa.VARCHAR(length=36), nullable=True),
        sa.Column("deprecated_by", sa.VARCHAR(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["deprecated_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["flow_registry_entries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["flow_definition_version_id"],
            ["flow_definition_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "version", name=op.f("uq_flow_registry_versions_entry_version")),
    )
    op.create_index(op.f("ix_flow_registry_versions_status"), "flow_registry_versions", ["status"], unique=False)
    op.create_index(
        op.f("ix_flow_registry_versions_published_by"), "flow_registry_versions", ["published_by"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_published_at"), "flow_registry_versions", ["published_at"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_published"), "flow_registry_versions", ["status", "published_at"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_flow_definition_version_id"),
        "flow_registry_versions",
        ["flow_definition_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_registry_versions_eval_suite_id"), "flow_registry_versions", ["eval_suite_id"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_entry_status"), "flow_registry_versions", ["entry_id", "status"], unique=False
    )
    op.create_index(op.f("ix_flow_registry_versions_entry_id"), "flow_registry_versions", ["entry_id"], unique=False)
    op.create_index(
        op.f("ix_flow_registry_versions_deprecated_by"), "flow_registry_versions", ["deprecated_by"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_created_by"), "flow_registry_versions", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_flow_registry_versions_created_at"), "flow_registry_versions", ["created_at"], unique=False
    )
    op.create_table(
        "flow_node_runs",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("orchestrator_run_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("flow_definition_version_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("node_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("node_type", sa.VARCHAR(length=64), nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), nullable=False),
        sa.Column("attempt", sa.INTEGER(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.TEXT(), nullable=True),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("trace_refs_json", sa.JSON(), nullable=False),
        sa.Column("token_usage_json", sa.JSON(), nullable=False),
        sa.Column("cost_estimate_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["flow_definition_version_id"],
            ["flow_definition_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["orchestrator_run_id"],
            ["orchestrator_agent_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_flow_node_runs_status"), "flow_node_runs", ["status"], unique=False)
    op.create_index(op.f("ix_flow_node_runs_started_at"), "flow_node_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_flow_node_runs_orchestrator"), "flow_node_runs", ["orchestrator_run_id"], unique=False)
    op.create_index(op.f("ix_flow_node_runs_node_type"), "flow_node_runs", ["node_type"], unique=False)
    op.create_index(
        op.f("ix_flow_node_runs_node"), "flow_node_runs", ["flow_definition_version_id", "node_id"], unique=False
    )
    op.create_index(
        op.f("ix_flow_node_runs_flow_version"), "flow_node_runs", ["flow_definition_version_id"], unique=False
    )
    op.create_index(op.f("ix_flow_node_runs_created_at"), "flow_node_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_flow_node_runs_completed_at"), "flow_node_runs", ["completed_at"], unique=False)
