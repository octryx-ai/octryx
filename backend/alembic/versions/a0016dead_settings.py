"""Drop what only the deleted agent loop used (WP-C4d): scenario profiles, context budget profiles, the system prompt
routing revisions and the models' planner context budget."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0016dead_settings"
down_revision: str | None = "a0015device_job_waiting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_scenario_profiles_owner_id"), table_name="scenario_profiles")
    op.drop_index(op.f("ix_scenario_profiles_project_id"), table_name="scenario_profiles")
    op.drop_index(op.f("ix_scenario_profiles_updated_at"), table_name="scenario_profiles")
    op.drop_table("scenario_profiles")
    op.drop_index(op.f("ix_context_budget_profiles_active_priority"), table_name="context_budget_profiles")
    op.drop_index(op.f("ix_context_budget_profiles_created_at"), table_name="context_budget_profiles")
    op.drop_index(op.f("ix_context_budget_profiles_priority"), table_name="context_budget_profiles")
    op.drop_index(op.f("ix_context_budget_profiles_trigger_pattern"), table_name="context_budget_profiles")
    op.drop_table("context_budget_profiles")
    op.drop_index(op.f("ix_prompt_config_revisions_config_key"), table_name="prompt_config_revisions")
    op.drop_index(op.f("ix_prompt_config_revisions_created_at"), table_name="prompt_config_revisions")
    op.drop_index(op.f("ix_prompt_config_revisions_created_by"), table_name="prompt_config_revisions")
    op.drop_index(op.f("ix_prompt_config_revisions_scope_config_version"), table_name="prompt_config_revisions")
    op.drop_table("prompt_config_revisions")
    op.drop_column("llm_models", "planner_context_budget")


def downgrade() -> None:
    op.add_column("llm_models", sa.Column("planner_context_budget", sa.INTEGER(), nullable=True))
    op.create_table(
        "prompt_config_revisions",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("scope_type", sa.VARCHAR(length=30), nullable=False),
        sa.Column("scope_id", sa.VARCHAR(length=200), nullable=True),
        sa.Column("config_key", sa.VARCHAR(length=240), nullable=False),
        sa.Column("variant_key", sa.VARCHAR(length=80), nullable=True),
        sa.Column("version", sa.INTEGER(), nullable=False),
        sa.Column("value", sa.TEXT(), nullable=True),
        sa.Column("value_checksum", sa.VARCHAR(length=64), nullable=False),
        sa.Column("change_source", sa.VARCHAR(length=60), nullable=False),
        sa.Column("created_by", sa.VARCHAR(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prompt_config_revisions_scope_config_version"),
        "prompt_config_revisions",
        ["scope_type", "scope_id", "config_key", "version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_config_revisions_created_by"), "prompt_config_revisions", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_prompt_config_revisions_created_at"), "prompt_config_revisions", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_prompt_config_revisions_config_key"), "prompt_config_revisions", ["config_key"], unique=False
    )
    op.create_table(
        "context_budget_profiles",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("trigger_pattern", sa.VARCHAR(length=255), nullable=False),
        sa.Column("base_budget", sa.INTEGER(), nullable=False),
        sa.Column("tool_budget", sa.INTEGER(), nullable=False),
        sa.Column("history_budget", sa.INTEGER(), nullable=False),
        sa.Column("entity_budget", sa.INTEGER(), nullable=False),
        sa.Column("memory_budget", sa.INTEGER(), nullable=False),
        sa.Column("priority", sa.INTEGER(), nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_context_budget_profiles_trigger_pattern"), "context_budget_profiles", ["trigger_pattern"], unique=False
    )
    op.create_index(op.f("ix_context_budget_profiles_priority"), "context_budget_profiles", ["priority"], unique=False)
    op.create_index(
        op.f("ix_context_budget_profiles_created_at"), "context_budget_profiles", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_context_budget_profiles_active_priority"),
        "context_budget_profiles",
        ["is_active", "priority"],
        unique=False,
    )
    op.create_table(
        "scenario_profiles",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("owner_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("project_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("name", sa.VARCHAR(length=200), nullable=False),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column("priority", sa.INTEGER(), nullable=False),
        sa.Column("match_config", sa.JSON(), nullable=True),
        sa.Column("planner_config", sa.JSON(), nullable=True),
        sa.Column("execution_config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.BOOLEAN(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scenario_profiles_updated_at"), "scenario_profiles", ["updated_at"], unique=False)
    op.create_index(op.f("ix_scenario_profiles_project_id"), "scenario_profiles", ["project_id"], unique=False)
    op.create_index(op.f("ix_scenario_profiles_owner_id"), "scenario_profiles", ["owner_id"], unique=False)
