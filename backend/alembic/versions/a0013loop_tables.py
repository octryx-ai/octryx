"""Drop the tables only the platform's own agent loop used (WP-C4b1): its LLM cache, context compactions, tool and
prefetch caches, the secure-work coding workspaces and the sub-agent groups."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0013loop_tables"
down_revision: str | None = "a0012device_engines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_llm_cache_entries_cache_scope"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_created_at"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_expires_at"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_model_id"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_prompt_hash"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_prompt_provider_model"), table_name="llm_cache_entries")
    op.drop_index(op.f("ix_llm_cache_entries_provider_id"), table_name="llm_cache_entries")
    op.drop_table("llm_cache_entries")
    op.drop_index(op.f("ix_runtime_context_compactions_created_at"), table_name="runtime_context_compactions")
    op.drop_index(op.f("ix_runtime_context_compactions_session_id"), table_name="runtime_context_compactions")
    op.drop_index(op.f("ix_runtime_context_compactions_session_index"), table_name="runtime_context_compactions")
    op.drop_index(op.f("ix_runtime_context_compactions_session_status"), table_name="runtime_context_compactions")
    op.drop_index(
        op.f("ix_runtime_context_compactions_source_first_message_id"), table_name="runtime_context_compactions"
    )
    op.drop_index(
        op.f("ix_runtime_context_compactions_source_last_message_id"), table_name="runtime_context_compactions"
    )
    op.drop_index(op.f("ix_runtime_context_compactions_status"), table_name="runtime_context_compactions")
    op.drop_index(op.f("ix_runtime_context_compactions_superseded_at"), table_name="runtime_context_compactions")
    op.drop_table("runtime_context_compactions")
    op.drop_index(op.f("ix_session_tool_cache_cached_at"), table_name="session_tool_cache")
    op.drop_index(op.f("ix_session_tool_cache_lookup"), table_name="session_tool_cache")
    op.drop_index(op.f("ix_session_tool_cache_params_hash"), table_name="session_tool_cache")
    op.drop_index(op.f("ix_session_tool_cache_session_id"), table_name="session_tool_cache")
    op.drop_index(op.f("ix_session_tool_cache_tool_name"), table_name="session_tool_cache")
    op.drop_table("session_tool_cache")
    op.drop_index(op.f("ix_work_coding_workspaces_branch"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_change_unit"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_change_unit_id"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_item_created"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_pipeline_run"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_pipeline_run_id"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_session_id"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_status"), table_name="work_coding_workspaces")
    op.drop_index(op.f("ix_work_coding_workspaces_work_item_id"), table_name="work_coding_workspaces")
    op.drop_table("work_coding_workspaces")
    op.drop_index(op.f("ix_sub_agent_groups_completed_at"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_created_at"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_parent_session_id"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_parent_status"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_resumed_at"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_status"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_timeout_at"), table_name="sub_agent_groups")
    op.drop_index(op.f("ix_sub_agent_groups_updated_at"), table_name="sub_agent_groups")
    op.drop_table("sub_agent_groups")
    op.drop_index(op.f("ix_prefetch_cache_completed_at"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_created_at"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_lookup"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_params_hash"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_session_id"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_status"), table_name="prefetch_cache")
    op.drop_index(op.f("ix_prefetch_cache_tool_name"), table_name="prefetch_cache")
    op.drop_table("prefetch_cache")


def downgrade() -> None:
    op.create_table(
        "prefetch_cache",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("tool_name", sa.VARCHAR(length=100), nullable=False),
        sa.Column("params_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.VARCHAR(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prefetch_cache_tool_name"), "prefetch_cache", ["tool_name"], unique=False)
    op.create_index(op.f("ix_prefetch_cache_status"), "prefetch_cache", ["status"], unique=False)
    op.create_index(op.f("ix_prefetch_cache_session_id"), "prefetch_cache", ["session_id"], unique=False)
    op.create_index(op.f("ix_prefetch_cache_params_hash"), "prefetch_cache", ["params_hash"], unique=False)
    op.create_index(
        op.f("ix_prefetch_cache_lookup"), "prefetch_cache", ["session_id", "tool_name", "params_hash"], unique=False
    )
    op.create_index(op.f("ix_prefetch_cache_created_at"), "prefetch_cache", ["created_at"], unique=False)
    op.create_index(op.f("ix_prefetch_cache_completed_at"), "prefetch_cache", ["completed_at"], unique=False)
    op.create_table(
        "sub_agent_groups",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("parent_session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), nullable=False),
        sa.Column("total_count", sa.INTEGER(), nullable=False),
        sa.Column("completed_count", sa.INTEGER(), nullable=False),
        sa.Column("failed_count", sa.INTEGER(), nullable=False),
        sa.Column("child_session_ids_json", sa.JSON(), nullable=False),
        sa.Column("child_statuses_json", sa.JSON(), nullable=False),
        sa.Column("resume_prompt", sa.TEXT(), nullable=True),
        sa.Column("timeout_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sub_agent_groups_updated_at"), "sub_agent_groups", ["updated_at"], unique=False)
    op.create_index(op.f("ix_sub_agent_groups_timeout_at"), "sub_agent_groups", ["timeout_at"], unique=False)
    op.create_index(op.f("ix_sub_agent_groups_status"), "sub_agent_groups", ["status"], unique=False)
    op.create_index(op.f("ix_sub_agent_groups_resumed_at"), "sub_agent_groups", ["resumed_at"], unique=False)
    op.create_index(
        op.f("ix_sub_agent_groups_parent_status"), "sub_agent_groups", ["parent_session_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_sub_agent_groups_parent_session_id"), "sub_agent_groups", ["parent_session_id"], unique=False
    )
    op.create_index(op.f("ix_sub_agent_groups_created_at"), "sub_agent_groups", ["created_at"], unique=False)
    op.create_index(op.f("ix_sub_agent_groups_completed_at"), "sub_agent_groups", ["completed_at"], unique=False)
    op.create_table(
        "work_coding_workspaces",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("work_item_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("pipeline_run_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("change_unit_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("repository_profile_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("provider", sa.VARCHAR(length=50), nullable=False),
        sa.Column("provider_instance", sa.VARCHAR(length=220), nullable=False),
        sa.Column("project_key", sa.VARCHAR(length=120), nullable=True),
        sa.Column("repository_name", sa.VARCHAR(length=220), nullable=False),
        sa.Column("repository_slug", sa.VARCHAR(length=220), nullable=False),
        sa.Column("repository_url", sa.TEXT(), nullable=True),
        sa.Column("base_branch", sa.VARCHAR(length=260), nullable=True),
        sa.Column("resolved_base_branch", sa.VARCHAR(length=260), nullable=True),
        sa.Column("feature_branch", sa.VARCHAR(length=260), nullable=False),
        sa.Column("base_commit", sa.VARCHAR(length=80), nullable=True),
        sa.Column("workspace_path", sa.TEXT(), nullable=False),
        sa.Column("source_repository_root", sa.TEXT(), nullable=True),
        sa.Column("source_evidence_cutoff", sa.DateTime(), nullable=True),
        sa.Column("restart_generation", sa.INTEGER(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=80), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), nullable=False),
        sa.Column("created_by", sa.VARCHAR(length=36), nullable=False),
        sa.Column("updated_by", sa.VARCHAR(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["change_unit_id"],
            ["work_item_change_units.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["work_coding_pipeline_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["repository_profile_id"],
            ["work_repository_profiles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["work_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_run_id",
            "change_unit_id",
            "restart_generation",
            name=op.f("uq_work_coding_workspace_run_unit_generation"),
        ),
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_work_item_id"), "work_coding_workspaces", ["work_item_id"], unique=False
    )
    op.create_index(op.f("ix_work_coding_workspaces_status"), "work_coding_workspaces", ["status"], unique=False)
    op.create_index(
        op.f("ix_work_coding_workspaces_session_id"), "work_coding_workspaces", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_pipeline_run_id"), "work_coding_workspaces", ["pipeline_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_pipeline_run"), "work_coding_workspaces", ["pipeline_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_item_created"),
        "work_coding_workspaces",
        ["work_item_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_change_unit_id"), "work_coding_workspaces", ["change_unit_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_change_unit"), "work_coding_workspaces", ["change_unit_id"], unique=False
    )
    op.create_index(
        op.f("ix_work_coding_workspaces_branch"),
        "work_coding_workspaces",
        ["repository_slug", "feature_branch"],
        unique=False,
    )
    op.create_table(
        "session_tool_cache",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("tool_name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("params_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("cached_at", sa.DateTime(), nullable=False),
        sa.Column("ttl_seconds", sa.INTEGER(), nullable=False),
        sa.Column("hit_count", sa.INTEGER(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_session_tool_cache_tool_name"), "session_tool_cache", ["tool_name"], unique=False)
    op.create_index(op.f("ix_session_tool_cache_session_id"), "session_tool_cache", ["session_id"], unique=False)
    op.create_index(op.f("ix_session_tool_cache_params_hash"), "session_tool_cache", ["params_hash"], unique=False)
    op.create_index(
        op.f("ix_session_tool_cache_lookup"),
        "session_tool_cache",
        ["session_id", "tool_name", "params_hash"],
        unique=False,
    )
    op.create_index(op.f("ix_session_tool_cache_cached_at"), "session_tool_cache", ["cached_at"], unique=False)
    op.create_table(
        "runtime_context_compactions",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("status", sa.VARCHAR(length=30), nullable=False),
        sa.Column("compaction_index", sa.INTEGER(), nullable=False),
        sa.Column("source_first_message_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("source_last_message_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("source_message_count", sa.INTEGER(), nullable=False),
        sa.Column("recent_message_count", sa.INTEGER(), nullable=False),
        sa.Column("summary_text", sa.TEXT(), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_superseded_at"),
        "runtime_context_compactions",
        ["superseded_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_status"), "runtime_context_compactions", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_source_last_message_id"),
        "runtime_context_compactions",
        ["source_last_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_source_first_message_id"),
        "runtime_context_compactions",
        ["source_first_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_session_status"),
        "runtime_context_compactions",
        ["session_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_session_index"),
        "runtime_context_compactions",
        ["session_id", "compaction_index"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_session_id"), "runtime_context_compactions", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_runtime_context_compactions_created_at"), "runtime_context_compactions", ["created_at"], unique=False
    )
    op.create_table(
        "llm_cache_entries",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("prompt_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("provider_id", sa.VARCHAR(length=100), nullable=False),
        sa.Column("model_id", sa.VARCHAR(length=200), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("hit_count", sa.INTEGER(), nullable=False),
        sa.Column("cache_scope", sa.VARCHAR(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_cache_entries_provider_id"), "llm_cache_entries", ["provider_id"], unique=False)
    op.create_index(
        op.f("ix_llm_cache_entries_prompt_provider_model"),
        "llm_cache_entries",
        ["prompt_hash", "provider_id", "model_id"],
        unique=False,
    )
    op.create_index(op.f("ix_llm_cache_entries_prompt_hash"), "llm_cache_entries", ["prompt_hash"], unique=False)
    op.create_index(op.f("ix_llm_cache_entries_model_id"), "llm_cache_entries", ["model_id"], unique=False)
    op.create_index(op.f("ix_llm_cache_entries_expires_at"), "llm_cache_entries", ["expires_at"], unique=False)
    op.create_index(op.f("ix_llm_cache_entries_created_at"), "llm_cache_entries", ["created_at"], unique=False)
    op.create_index(op.f("ix_llm_cache_entries_cache_scope"), "llm_cache_entries", ["cache_scope"], unique=False)
