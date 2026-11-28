"""Drop the tables no code writes or reads any more, with the retention policies of ``agent_trace_runs``
and the unread trace compaction keys of each Workspace's ``trace_capture`` config."""

# ruff: noqa: E501 - generated schema: one statement per line

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0002unwired"
down_revision: str | None = "a0001baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DROPPED_TABLES = (
    "agent_trace_spans",
    "agent_trace_runs",
    "agent_trace_alert_rules",
    "paused_entities",
    "data_redaction_logs",
    "data_classification_tags",
    "data_classification_policies",
    "secret_scope_bindings",
    "quota_usage_forecasts",
)

DEAD_TRACE_CAPTURE_KEYS = (
    "compact_max_string",
    "compact_max_list_items",
    "compact_max_dict_items",
    "always_full_on_error",
    "always_full_on_sensitive_tools",
)


def _strip_dead_trace_capture_keys() -> None:
    projects = sa.table("projects", sa.column("id", sa.String()), sa.column("config", sa.JSON()))
    connection = op.get_bind()
    for project_id, config in connection.execute(sa.select(projects.c.id, projects.c.config)).all():
        trace_capture = config.get("trace_capture") if isinstance(config, dict) else None
        if not isinstance(trace_capture, dict) or not set(DEAD_TRACE_CAPTURE_KEYS) & trace_capture.keys():
            continue
        kept = {key: value for key, value in trace_capture.items() if key not in DEAD_TRACE_CAPTURE_KEYS}
        connection.execute(projects.update().where(projects.c.id == project_id)
                           .values(config={**config, "trace_capture": kept}))


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM retention_policies WHERE entity_type = 'agent_trace_runs'"))
    _strip_dead_trace_capture_keys()
    for table in DROPPED_TABLES:
        op.drop_table(table)


# Recreates the tables empty; their rows and the deleted retention policies are not restored.
def downgrade() -> None:
    op.create_table(
        "quota_usage_forecasts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("forecasted_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=False),
        sa.Column("forecasted_cost", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("actual_cost", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["budget_policies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quota_forecast_policy_period", "quota_usage_forecasts", ["policy_id", "period_key"], unique=True
    )
    op.create_index(op.f("ix_quota_usage_forecasts_policy_id"), "quota_usage_forecasts", ["policy_id"], unique=False)
    op.create_table(
        "secret_scope_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("secret_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("entity_label", sa.String(length=200), nullable=False),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_by", sa.String(length=36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["stored_secrets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_id", "entity_type", "entity_id", name="uq_secret_scope_binding"),
    )
    op.create_index("ix_secret_scope_bindings_active", "secret_scope_bindings", ["is_active"], unique=False)
    op.create_index(op.f("ix_secret_scope_bindings_created_at"), "secret_scope_bindings", ["created_at"], unique=False)
    op.create_index(op.f("ix_secret_scope_bindings_entity_id"), "secret_scope_bindings", ["entity_id"], unique=False)
    op.create_index(
        op.f("ix_secret_scope_bindings_entity_type"), "secret_scope_bindings", ["entity_type"], unique=False
    )
    op.create_index(op.f("ix_secret_scope_bindings_is_active"), "secret_scope_bindings", ["is_active"], unique=False)
    op.create_index(
        "ix_secret_scope_bindings_secret_entity", "secret_scope_bindings", ["secret_id", "entity_type"], unique=False
    )
    op.create_index(op.f("ix_secret_scope_bindings_secret_id"), "secret_scope_bindings", ["secret_id"], unique=False)
    op.create_table(
        "data_classification_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("default_classification", sa.String(length=30), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("export_action", sa.String(length=20), nullable=False),
        sa.Column("auto_redact_pii", sa.Boolean(), nullable=False),
        sa.Column("require_export_audit", sa.Boolean(), nullable=False),
        sa.Column("data_residency", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dcp_classification", "data_classification_policies", ["default_classification"], unique=False)
    op.create_index("ix_dcp_entity_type", "data_classification_policies", ["entity_type"], unique=False)
    op.create_index("ix_dcp_project_id", "data_classification_policies", ["project_id"], unique=False)
    op.create_table(
        "data_classification_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=200), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("pii_detected", sa.Boolean(), nullable=False),
        sa.Column("pii_types", sa.JSON(), nullable=False),
        sa.Column("retention_days_override", sa.Integer(), nullable=True),
        sa.Column("data_residency", sa.String(length=100), nullable=True),
        sa.Column("redaction_applied", sa.Boolean(), nullable=False),
        sa.Column("redaction_config", sa.JSON(), nullable=False),
        sa.Column("sensitivity_tags", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("classified_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["classified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_data_classification_tags_created_at"), "data_classification_tags", ["created_at"], unique=False
    )
    op.create_index("ix_dct_classification", "data_classification_tags", ["classification"], unique=False)
    op.create_index("ix_dct_entity", "data_classification_tags", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_dct_pii_present", "data_classification_tags", ["pii_detected"], unique=False)
    op.create_index("ix_dct_project_id", "data_classification_tags", ["project_id"], unique=False)
    op.create_table(
        "data_redaction_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=200), nullable=False),
        sa.Column("redaction_reason", sa.String(length=50), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("pii_types_redacted", sa.JSON(), nullable=False),
        sa.Column("redacted_fields", sa.JSON(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_data_redaction_logs_created_at"), "data_redaction_logs", ["created_at"], unique=False)
    op.create_index("ix_drl_classification", "data_redaction_logs", ["classification"], unique=False)
    op.create_index("ix_drl_created_at", "data_redaction_logs", ["created_at"], unique=False)
    op.create_index("ix_drl_entity", "data_redaction_logs", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_drl_redaction_reason", "data_redaction_logs", ["redaction_reason"], unique=False)
    op.create_table(
        "paused_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("previous_is_active", sa.Boolean(), nullable=True),
        sa.Column("paused_by_kill_switch_id", sa.String(length=36), nullable=True),
        sa.Column("incident_id", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["paused_by_kill_switch_id"],
            ["kill_switch_logs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paused_entities_incident", "paused_entities", ["incident_id"], unique=False)
    op.create_index(op.f("ix_paused_entities_project_id"), "paused_entities", ["project_id"], unique=False)
    op.create_index("ix_paused_entities_type_id", "paused_entities", ["entity_type", "entity_id"], unique=True)
    op.create_table(
        "agent_trace_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("agent_definition_id", sa.String(length=36), nullable=True),
        sa.Column("flow_id", sa.String(length=120), nullable=True),
        sa.Column("run_kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"],
            ["agent_definitions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_trace_runs_agent_definition_id"), "agent_trace_runs", ["agent_definition_id"], unique=False
    )
    op.create_index(op.f("ix_agent_trace_runs_created_at"), "agent_trace_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_ended_at"), "agent_trace_runs", ["ended_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_flow_id"), "agent_trace_runs", ["flow_id"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_message_id"), "agent_trace_runs", ["message_id"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_project_id"), "agent_trace_runs", ["project_id"], unique=False)
    op.create_index(
        "ix_agent_trace_runs_project_started", "agent_trace_runs", ["project_id", "started_at"], unique=False
    )
    op.create_index("ix_agent_trace_runs_project_status", "agent_trace_runs", ["project_id", "status"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_run_kind"), "agent_trace_runs", ["run_kind"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_session_id"), "agent_trace_runs", ["session_id"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_started_at"), "agent_trace_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_status"), "agent_trace_runs", ["status"], unique=False)
    op.create_index(op.f("ix_agent_trace_runs_trace_id"), "agent_trace_runs", ["trace_id"], unique=True)
    op.create_index(op.f("ix_agent_trace_runs_updated_at"), "agent_trace_runs", ["updated_at"], unique=False)
    op.create_table(
        "agent_trace_spans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_run_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=64), nullable=False),
        sa.Column("parent_span_id", sa.String(length=64), nullable=True),
        sa.Column("span_type", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("span_metadata", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["trace_run_id"],
            ["agent_trace_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_trace_spans_created_at"), "agent_trace_spans", ["created_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_ended_at"), "agent_trace_spans", ["ended_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_parent_span_id"), "agent_trace_spans", ["parent_span_id"], unique=False)
    op.create_index(
        "ix_agent_trace_spans_run_started", "agent_trace_spans", ["trace_run_id", "started_at"], unique=False
    )
    op.create_index(op.f("ix_agent_trace_spans_span_id"), "agent_trace_spans", ["span_id"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_span_type"), "agent_trace_spans", ["span_type"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_started_at"), "agent_trace_spans", ["started_at"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_status"), "agent_trace_spans", ["status"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_trace_id"), "agent_trace_spans", ["trace_id"], unique=False)
    op.create_index(op.f("ix_agent_trace_spans_trace_run_id"), "agent_trace_spans", ["trace_run_id"], unique=False)
    op.create_index("ix_agent_trace_spans_trace_type", "agent_trace_spans", ["trace_id", "span_type"], unique=False)
    op.create_table(
        "agent_trace_alert_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("condition_json", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("notification_channel", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_trace_alert_rules_created_at"), "agent_trace_alert_rules", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_agent_trace_alert_rules_enabled"), "agent_trace_alert_rules", ["enabled"], unique=False)
    op.create_index(
        op.f("ix_agent_trace_alert_rules_project_id"), "agent_trace_alert_rules", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_agent_trace_alert_rules_severity"), "agent_trace_alert_rules", ["severity"], unique=False)
    op.create_index(
        op.f("ix_agent_trace_alert_rules_updated_at"), "agent_trace_alert_rules", ["updated_at"], unique=False
    )
