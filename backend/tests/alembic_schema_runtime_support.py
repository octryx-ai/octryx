"""Schema assertions for the runtime, identity, tracing, flow, platform and session tables after upgrade."""

from __future__ import annotations

from sqlalchemy.engine.reflection import Inspector


def assert_runtime_tables(table_names: set[str]) -> None:
    """Runtime, identity, tracing, flow and platform tables."""
    assert "exec_policy_configs" in table_names
    assert "system_config" in table_names
    assert "context_budget_profiles" in table_names
    assert "session_tool_cache" in table_names
    assert "context_checkpoints" in table_names
    assert "prefetch_rules" not in table_names
    assert "prefetch_cache" in table_names
    assert "identity_providers" in table_names
    assert "user_identities" in table_names
    assert "oauth_sessions" in table_names
    assert "refresh_tokens" in table_names
    assert "change_previews" in table_names
    assert "budget_policies" in table_names
    assert "task_queue_entries" in table_names
    assert "prompt_config_revisions" in table_names
    # Durable runtime tables (created by the durable runtime tables migration)
    assert "distributed_locks" in table_names
    assert "resume_checkpoints" in table_names
    assert "analytics_daily" in table_names
    assert "report_exports" in table_names
    assert "api_request_metrics" in table_names
    assert "platform_health_checks" in table_names
    assert "agent_trace_runs" in table_names
    assert "agent_trace_spans" in table_names
    assert "agent_trace_alert_rules" in table_names
    # The evaluation suites, workflow gates and agent registry are retired; checks store their results.
    assert "evaluation_suites" not in table_names and "workflow_gate_definitions" not in table_names
    assert "workflow_check_results" in table_names
    assert "flow_definitions" in table_names
    assert "flow_definition_versions" in table_names
    assert "flow_node_runs" in table_names
    assert "runtime_processes" in table_names
    assert "runtime_context_compactions" in table_names
    assert "circuit_breaker_states" in table_names
    assert "tool_result_compression_log" in table_names
    assert "session_entities" in table_names
    assert "design_artifacts" in table_names
    assert "database_connectors" in table_names
    assert "sub_agent_groups" in table_names
    assert "sla_definitions" in table_names
    assert "feature_flags" in table_names
    assert "session_collaborators" in table_names
    assert "session_handovers" in table_names
    assert "stored_secrets" in table_names
    assert "teams" in table_names
    assert "agent_groups" in table_names
    assert "agent_definitions" in table_names
    assert "scenario_profiles" in table_names


def assert_identity_and_tracing_indexes(inspector: Inspector, table_names: set[str]) -> None:
    assert "ix_exec_policy_configs_project_id" in {idx["name"] for idx in inspector.get_indexes("exec_policy_configs")}
    assert "ix_context_budget_profiles_active_priority" in {
        idx["name"] for idx in inspector.get_indexes("context_budget_profiles")
    }
    assert "ix_session_tool_cache_lookup" in {idx["name"] for idx in inspector.get_indexes("session_tool_cache")}
    assert "ix_context_checkpoints_session_id" in {idx["name"] for idx in inspector.get_indexes("context_checkpoints")}
    # Durable runtime tables
    assert "distributed_locks" in table_names
    assert "resume_checkpoints" in table_names
    assert "ix_prefetch_cache_lookup" in {idx["name"] for idx in inspector.get_indexes("prefetch_cache")}
    assert "ix_identity_providers_provider_type" in {idx["name"] for idx in inspector.get_indexes("identity_providers")}
    assert "ix_user_identities_provider_subject" in {idx["name"] for idx in inspector.get_indexes("user_identities")}
    assert "ix_oauth_sessions_state" in {idx["name"] for idx in inspector.get_indexes("oauth_sessions")}
    assert "ix_refresh_tokens_token_hash" in {idx["name"] for idx in inspector.get_indexes("refresh_tokens")}
    assert "ix_change_previews_request_fingerprint" in {idx["name"] for idx in inspector.get_indexes("change_previews")}
    assert "ix_budget_policies_user_project" in {idx["name"] for idx in inspector.get_indexes("budget_policies")}
    assert "ix_task_queue_entries_status" in {idx["name"] for idx in inspector.get_indexes("task_queue_entries")}
    prompt_revision_indexes = {idx["name"] for idx in inspector.get_indexes("prompt_config_revisions")}
    assert "ix_prompt_config_revisions_scope_config_version" in prompt_revision_indexes
    assert "ix_prompt_config_revisions_config_key" in prompt_revision_indexes
    assert "ix_analytics_daily_scope_date" in {idx["name"] for idx in inspector.get_indexes("analytics_daily")}
    assert "ix_report_exports_created_at" in {idx["name"] for idx in inspector.get_indexes("report_exports")}
    assert "ix_api_request_metrics_created_at" in {idx["name"] for idx in inspector.get_indexes("api_request_metrics")}
    assert "ix_agent_trace_runs_project_started" in {idx["name"] for idx in inspector.get_indexes("agent_trace_runs")}
    assert "ix_agent_trace_spans_run_started" in {idx["name"] for idx in inspector.get_indexes("agent_trace_spans")}
    assert "ix_agent_trace_alert_rules_enabled" in {
        idx["name"] for idx in inspector.get_indexes("agent_trace_alert_rules")
    }


def assert_flow_runtime_and_platform_indexes(inspector: Inspector, table_names: set[str]) -> None:
    assert "ix_flow_definitions_project_status" in {idx["name"] for idx in inspector.get_indexes("flow_definitions")}
    assert "ix_flow_definition_versions_flow_status" in {
        idx["name"] for idx in inspector.get_indexes("flow_definition_versions")
    }
    flow_node_run_indexes = {idx["name"] for idx in inspector.get_indexes("flow_node_runs")}
    assert {
        "ix_flow_node_runs_orchestrator",
        "ix_flow_node_runs_flow_version",
        "ix_flow_node_runs_node",
        "ix_flow_node_runs_status",
    } <= flow_node_run_indexes
    runtime_process_indexes = {idx["name"] for idx in inspector.get_indexes("runtime_processes")}
    assert {
        "ix_runtime_processes_session_id",
        "ix_runtime_processes_project_id",
        "ix_runtime_processes_user_id",
        "ix_runtime_processes_status",
        "ix_runtime_processes_started_at",
        "ix_runtime_processes_completed_at",
    } <= runtime_process_indexes
    runtime_context_compaction_indexes = {idx["name"] for idx in inspector.get_indexes("runtime_context_compactions")}
    assert {
        "ix_runtime_context_compactions_session_id",
        "ix_runtime_context_compactions_status",
        "ix_runtime_context_compactions_session_status",
        "ix_runtime_context_compactions_session_index",
        "ix_runtime_context_compactions_created_at",
    } <= runtime_context_compaction_indexes
    assert "ix_circuit_breaker_states_state" in {idx["name"] for idx in inspector.get_indexes("circuit_breaker_states")}
    assert "ix_tool_result_compression_log_session_tool" in {
        idx["name"] for idx in inspector.get_indexes("tool_result_compression_log")
    }
    assert "ix_session_entities_unique" in {idx["name"] for idx in inspector.get_indexes("session_entities")}
    assert "ix_design_artifacts_project_kind" in {idx["name"] for idx in inspector.get_indexes("design_artifacts")}
    assert "ix_database_connectors_db_type" in {idx["name"] for idx in inspector.get_indexes("database_connectors")}
    assert "database_query_tool_runs" in table_names
    database_query_tool_run_indexes = {idx["name"] for idx in inspector.get_indexes("database_query_tool_runs")}
    assert {
        "ix_database_query_tool_runs_connector_status",
        "ix_database_query_tool_runs_project_started",
        "ix_database_query_tool_runs_session_started",
        "ix_database_query_tool_runs_tool_started",
    } <= database_query_tool_run_indexes


def assert_team_workspace_and_session_event_indexes(inspector: Inspector) -> None:
    assert "ix_sub_agent_groups_status" in {idx["name"] for idx in inspector.get_indexes("sub_agent_groups")}
    assert "ix_sla_breaches_definition_created" in {idx["name"] for idx in inspector.get_indexes("sla_breaches")}
    assert "ix_feature_flags_key" in {idx["name"] for idx in inspector.get_indexes("feature_flags")}
    assert "ix_session_collaborators_role" in {idx["name"] for idx in inspector.get_indexes("session_collaborators")}
    assert "ix_session_handovers_status" in {idx["name"] for idx in inspector.get_indexes("session_handovers")}
    assert "ix_stored_secrets_tool_name" in {idx["name"] for idx in inspector.get_indexes("stored_secrets")}
    stored_secret_columns = {column["name"]: column for column in inspector.get_columns("stored_secrets")}
    assert stored_secret_columns["secret_type"]["type"].length >= 200
    assert "ix_teams_created_by" in {idx["name"] for idx in inspector.get_indexes("teams")}
    assert "ix_agent_groups_slug" in {idx["name"] for idx in inspector.get_indexes("agent_groups")}
    assert "ix_agent_definitions_runtime_target_id" in {
        idx["name"] for idx in inspector.get_indexes("agent_definitions")
    }
    assert "ix_scenario_profiles_updated_at" in {idx["name"] for idx in inspector.get_indexes("scenario_profiles")}
    assert "ix_webhooks_created_at" in {idx["name"] for idx in inspector.get_indexes("webhooks")}
    assert "ix_webhook_events_received_at" in {idx["name"] for idx in inspector.get_indexes("webhook_events")}
    assert "ix_data_export_jobs_scope" in {idx["name"] for idx in inspector.get_indexes("data_export_jobs")}
    assert "ix_data_import_jobs_type_created" in {idx["name"] for idx in inspector.get_indexes("data_import_jobs")}
    assert "ix_agent_workers_project_active" in {idx["name"] for idx in inspector.get_indexes("agent_workers")}
    assert "ix_capability_types_active_kind" in {idx["name"] for idx in inspector.get_indexes("capability_types")}
    assert "ix_workspace_capability_bindings_workspace_kind" in {
        idx["name"] for idx in inspector.get_indexes("workspace_capability_bindings")
    }
    assert "ix_workspace_policy_workspace_id" in {idx["name"] for idx in inspector.get_indexes("workspace_policy")}
    # TaskQueueEntry new columns & indexes
    queue_idx = {idx["name"] for idx in inspector.get_indexes("task_queue_entries")}
    assert "ix_task_queue_entries_heartbeat" in queue_idx
    # SessionEvent WAL table indexes
    session_events_idx = {idx["name"] for idx in inspector.get_indexes("session_events")}
    assert "ix_session_events_session_index" in session_events_idx
    assert "ix_session_events_session_type" in session_events_idx
    assert "ix_session_events_session" in session_events_idx
    assert "ix_session_events_event_type" in session_events_idx


def assert_session_and_queue_columns(inspector: Inspector) -> None:
    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    assert {"parent_session_id", "sub_agent_depth"} <= session_columns
    assert "ix_sessions_parent_session_id" in {idx["name"] for idx in inspector.get_indexes("sessions")}

    agent_definition_columns = {column["name"] for column in inspector.get_columns("agent_definitions")}
    assert "skill_preferences_json" in agent_definition_columns

    # sessions.idempotency_key + run_status + recovery_policy
    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    assert "idempotency_key" in session_cols
    assert "run_status" in session_cols
    assert "recovery_policy" in session_cols
    # messages.idempotency_key
    msg_cols = {c["name"] for c in inspector.get_columns("messages")}
    assert "idempotency_key" in msg_cols

    # sessions.flow_definition_version_id + flow_node_id
    session_cols = {c["name"] for c in inspector.get_columns("sessions")}
    assert "flow_definition_version_id" in session_cols
    assert "flow_node_id" in session_cols

    # TaskQueueEntry new columns
    queue_cols = {c["name"] for c in inspector.get_columns("task_queue_entries")}
    assert "last_heartbeat" in queue_cols
    assert "timeout_minutes" in queue_cols

    # SessionEvent columns
    session_events_cols = {c["name"] for c in inspector.get_columns("session_events")}
    assert "session_id" in session_events_cols
    assert "event_type" in session_events_cols
    assert "from_status" in session_events_cols
    assert "to_status" in session_events_cols
    assert "from_run_status" in session_events_cols
    assert "to_run_status" in session_events_cols
    assert "actor" in session_events_cols
    assert "trigger" in session_events_cols
    assert "event_index" in session_events_cols
