"""Schema assertions for the work item, coding pipeline, CI/CD, connector watcher and federation tables."""

from __future__ import annotations

from sqlalchemy.engine.reflection import Inspector


def assert_work_and_connector_tables(table_names: set[str]) -> None:
    """Workspace, comparison, work item, CI/CD, connector and federation tables."""
    assert "webhooks" in table_names
    assert "webhook_events" in table_names
    assert "data_export_jobs" in table_names
    assert "data_import_jobs" in table_names
    assert "agent_workers" in table_names
    assert "capability_types" in table_names
    assert "workspace_capability_bindings" in table_names
    assert "workspace_policy" in table_names
    assert "research_policy_profiles" in table_names
    assert "research_policy_profile_versions" in table_names
    assert "workspace_research_policy_assignments" in table_names
    assert "skill_usage_events" in table_names
    # SessionEvent WAL table
    assert "session_events" in table_names
    assert "work_item_sync_configs" in table_names
    assert "work_items" in table_names
    assert "work_item_sync_runs" in table_names
    assert "work_item_workflow_definitions" in table_names
    assert "work_item_state_events" in table_names
    assert "work_repository_profiles" in table_names
    assert "work_item_change_units" in table_names
    assert "work_pull_requests" in table_names
    assert "work_engineering_profiles" in table_names
    assert "work_reviewer_overrides" in table_names
    assert "work_change_plans" in table_names
    assert "work_change_plan_decisions" in table_names
    assert "work_coding_policies" in table_names
    assert "work_technology_baselines" in table_names
    assert "work_coding_pipeline_configs" in table_names
    assert "work_coding_pipeline_runs" in table_names
    assert "work_coding_pipeline_stages" in table_names
    assert "work_coding_review_events" in table_names
    assert "work_coding_audit_events" in table_names
    assert "work_cicd_provider_configs" in table_names
    assert "work_cicd_builds" in table_names
    assert "work_cicd_pipeline_traces" in table_names
    assert "work_cicd_findings" in table_names
    assert "work_cicd_action_policies" in table_names
    assert "work_cicd_action_requests" in table_names
    assert "connector_watchers" in table_names
    assert "connector_watcher_events" in table_names
    assert "connector_watcher_rules" in table_names
    assert "connector_watcher_rule_decisions" in table_names
    assert "engineering_knowledge_federation_feeds" in table_names
    assert "engineering_knowledge_federation_packages" in table_names
    assert "engineering_knowledge_federation_sync_runs" in table_names


def assert_cicd_action_and_connector_indexes(inspector: Inspector) -> None:
    action_policy_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_action_policies")}
    assert {
        "ix_work_cicd_action_policies_project_active",
        "ix_work_cicd_action_policies_provider",
        "ix_work_cicd_action_policies_effect",
    } <= action_policy_indexes
    action_request_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_action_requests")}
    assert {
        "ix_work_cicd_action_requests_item_created",
        "ix_work_cicd_action_requests_provider",
        "ix_work_cicd_action_requests_policy",
        "ix_work_cicd_action_requests_status",
        "ix_work_cicd_action_requests_action",
    } <= action_request_indexes
    cicd_finding_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_findings")}
    assert {
        "ix_work_cicd_findings_item_created",
        "ix_work_cicd_findings_provider",
        "ix_work_cicd_findings_build",
        "ix_work_cicd_findings_trace",
        "ix_work_cicd_findings_status",
        "ix_work_cicd_findings_event_status",
        "ix_work_cicd_findings_commit",
    } <= cicd_finding_indexes
    connector_watcher_indexes = {idx["name"] for idx in inspector.get_indexes("connector_watchers")}
    assert {
        "ix_connector_watchers_connector_active",
        "ix_connector_watchers_project_status",
        "ix_connector_watchers_mode",
    } <= connector_watcher_indexes
    connector_event_indexes = {idx["name"] for idx in inspector.get_indexes("connector_watcher_events")}
    assert {
        "ix_connector_watcher_events_watcher_received",
        "ix_connector_watcher_events_status",
        "ix_connector_watcher_events_payload_hash",
        "ix_connector_watcher_events_external",
        "ix_connector_watcher_events_dead_letter",
    } <= connector_event_indexes
    connector_rule_indexes = {idx["name"] for idx in inspector.get_indexes("connector_watcher_rules")}
    assert {
        "ix_connector_watcher_rules_project_active",
        "ix_connector_watcher_rules_connector_active",
        "ix_connector_watcher_rules_priority",
        "ix_connector_watcher_rules_status",
    } <= connector_rule_indexes
    connector_rule_decision_indexes = {idx["name"] for idx in inspector.get_indexes("connector_watcher_rule_decisions")}
    assert {
        "ix_connector_watcher_rule_decisions_event",
        "ix_connector_watcher_rule_decisions_rule",
        "ix_connector_watcher_rule_decisions_action",
    } <= connector_rule_decision_indexes


def assert_federation_indexes(inspector: Inspector) -> None:
    federation_feed_indexes = {idx["name"] for idx in inspector.get_indexes("engineering_knowledge_federation_feeds")}
    assert {
        "ix_engineering_knowledge_federation_feeds_type_status",
        "ix_engineering_knowledge_federation_feeds_publisher",
    } <= federation_feed_indexes
    federation_package_indexes = {
        idx["name"] for idx in inspector.get_indexes("engineering_knowledge_federation_packages")
    }
    assert {
        "ix_engineering_knowledge_federation_packages_feed",
        "ix_engineering_knowledge_federation_packages_status_review",
        "ix_engineering_knowledge_federation_packages_package",
    } <= federation_package_indexes
    federation_sync_indexes = {
        idx["name"] for idx in inspector.get_indexes("engineering_knowledge_federation_sync_runs")
    }
    # The model's 64-character name for the (operation, started_at) index exceeds PostgreSQL's identifier
    # limit, so the schema creates it as ``ix_ekf_sync_runs_operation_started``.
    assert {
        "ix_engineering_knowledge_federation_sync_runs_feed_started",
        "ix_engineering_knowledge_federation_sync_runs_status_started",
        "ix_ekf_sync_runs_operation_started",
    } <= federation_sync_indexes


def assert_work_repository_and_pipeline_indexes(inspector: Inspector) -> None:
    work_state_event_indexes = {idx["name"] for idx in inspector.get_indexes("work_item_state_events")}
    assert "ix_work_item_state_events_item_created" in work_state_event_indexes
    work_workflow_indexes = {idx["name"] for idx in inspector.get_indexes("work_item_workflow_definitions")}
    assert "ix_work_item_workflows_project_active" in work_workflow_indexes
    repository_profile_indexes = {idx["name"] for idx in inspector.get_indexes("work_repository_profiles")}
    assert "ix_work_repository_profiles_project_active" in repository_profile_indexes
    assert "ix_work_repository_profiles_technology_baseline" in repository_profile_indexes
    repository_profile_columns = {column["name"] for column in inspector.get_columns("work_repository_profiles")}
    assert {
        "setup_commands_json",
        "build_commands_json",
        "test_commands_json",
        "lint_commands_json",
        "format_commands_json",
        "package_commands_json",
        "local_run_commands_json",
        "builder_runtime_image",
        "required_env_vars_json",
        "secret_references_json",
        "protected_paths_json",
        "hotspot_files_json",
        "artifact_paths_json",
        "coverage_report_paths_json",
        "test_report_paths_json",
        "multi_repo_dependencies_json",
    } <= repository_profile_columns
    baseline_indexes = {idx["name"] for idx in inspector.get_indexes("work_technology_baselines")}
    assert "ix_work_technology_baselines_project_active" in baseline_indexes
    assert "ix_work_technology_baselines_repository_profile" in baseline_indexes
    pipeline_config_indexes = {idx["name"] for idx in inspector.get_indexes("work_coding_pipeline_configs")}
    assert "ix_work_coding_pipeline_configs_project_active" in pipeline_config_indexes
    pipeline_run_indexes = {idx["name"] for idx in inspector.get_indexes("work_coding_pipeline_runs")}
    assert "ix_work_coding_pipeline_runs_item_created" in pipeline_run_indexes
    pipeline_stage_indexes = {idx["name"] for idx in inspector.get_indexes("work_coding_pipeline_stages")}
    assert "ix_work_coding_pipeline_stages_run_order" in pipeline_stage_indexes
    review_event_indexes = {idx["name"] for idx in inspector.get_indexes("work_coding_review_events")}
    assert {
        "ix_work_coding_review_events_item_created",
        "ix_work_coding_review_events_change_unit",
        "ix_work_coding_review_events_file",
        "ix_work_coding_review_events_type",
    } <= review_event_indexes
    audit_event_indexes = {idx["name"] for idx in inspector.get_indexes("work_coding_audit_events")}
    assert {
        "ix_work_coding_audit_events_item_created",
        "ix_work_coding_audit_events_type",
        "ix_work_coding_audit_events_pipeline_run",
        "ix_work_coding_audit_events_pr",
        "ix_work_coding_audit_events_commit",
    } <= audit_event_indexes


def assert_cicd_pull_request_and_change_plan_indexes(inspector: Inspector) -> None:
    cicd_provider_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_provider_configs")}
    assert {
        "ix_work_cicd_provider_configs_project_active",
        "ix_work_cicd_provider_configs_provider",
        "ix_work_cicd_provider_configs_status",
    } <= cicd_provider_indexes
    cicd_build_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_builds")}
    assert {
        "ix_work_cicd_builds_work_item_created",
        "ix_work_cicd_builds_provider_job",
        "ix_work_cicd_builds_status",
        "ix_work_cicd_builds_commit",
        "ix_work_cicd_builds_pr",
    } <= cicd_build_indexes
    cicd_trace_indexes = {idx["name"] for idx in inspector.get_indexes("work_cicd_pipeline_traces")}
    assert {
        "ix_work_cicd_pipeline_traces_work_item_created",
        "ix_work_cicd_pipeline_traces_build",
        "ix_work_cicd_pipeline_traces_provider_job",
        "ix_work_cicd_pipeline_traces_status",
        "ix_work_cicd_pipeline_traces_commit",
        "ix_work_cicd_pipeline_traces_pr",
    } <= cicd_trace_indexes
    change_unit_indexes = {idx["name"] for idx in inspector.get_indexes("work_item_change_units")}
    assert "ix_work_item_change_units_item_order" in change_unit_indexes
    pull_request_indexes = {idx["name"] for idx in inspector.get_indexes("work_pull_requests")}
    assert {
        "ix_work_pull_requests_item_updated",
        "ix_work_pull_requests_change_unit",
        "ix_work_pull_requests_repository_profile",
        "ix_work_pull_requests_status",
        "ix_work_pull_requests_build_status",
        "ix_work_pull_requests_target_branch",
    } <= pull_request_indexes
    engineering_profile_indexes = {idx["name"] for idx in inspector.get_indexes("work_engineering_profiles")}
    assert "ix_work_engineering_profiles_user_active" in engineering_profile_indexes
    reviewer_override_indexes = {idx["name"] for idx in inspector.get_indexes("work_reviewer_overrides")}
    assert "ix_work_reviewer_overrides_item_created" in reviewer_override_indexes
    change_plan_indexes = {idx["name"] for idx in inspector.get_indexes("work_change_plans")}
    assert "ix_work_change_plans_item_status" in change_plan_indexes
    change_plan_decision_indexes = {idx["name"] for idx in inspector.get_indexes("work_change_plan_decisions")}
    assert "ix_work_change_plan_decisions_plan_created" in change_plan_decision_indexes


def assert_session_event_and_work_item_sync_indexes(inspector: Inspector) -> None:
    session_events_idx = {idx["name"] for idx in inspector.get_indexes("session_events")}
    assert "ix_session_events_created_at" in session_events_idx
    work_item_sync_config_indexes = {idx["name"] for idx in inspector.get_indexes("work_item_sync_configs")}
    work_item_indexes = {idx["name"] for idx in inspector.get_indexes("work_items")}
    work_item_sync_run_indexes = {idx["name"] for idx in inspector.get_indexes("work_item_sync_runs")}
    assert {
        "ix_work_item_sync_configs_project_active",
        "ix_work_item_sync_configs_source",
    } <= work_item_sync_config_indexes
    assert {
        "ix_work_items_project_state",
        "ix_work_items_source_project_key",
        "ix_work_items_source_status",
        "ix_work_items_sync_config_id",
        "ix_work_items_sync_state",
        "ix_work_items_source_key",
        "ix_work_items_updated",
    } <= work_item_indexes
    assert {
        "ix_work_item_sync_runs_config_created",
        "ix_work_item_sync_runs_status",
    } <= work_item_sync_run_indexes
