import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class WorkItemSyncConfig(Base):
    __tablename__ = "work_item_sync_configs"
    __table_args__ = (
        Index("ix_work_item_sync_configs_project_active", "project_id", "is_active"),
        Index("ix_work_item_sync_configs_source", "source_type", "source_instance"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    source_type = Column(String(50), nullable=False, default="jira", index=True)
    source_instance = Column(String(220), nullable=False, default="default")
    connector_name = Column(String(220), nullable=True)  # free-text label; the connection when connection_id is unset
    # The Workspace connection the intake reads through: a named connection's id, or
    # ``default`` (the connector's own entry). Required for new intakes; resolved at run time.
    connection_id = Column(String(64), nullable=True, index=True)
    filters_json = Column(JSON, default=dict, nullable=False)
    field_mapping_json = Column(JSON, default=dict, nullable=False)
    sync_options_json = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String(50), nullable=True)
    last_sync_summary_json = Column(JSON, default=dict, nullable=False)
    # At most one run per configuration (syncs run every minute); an expired lease is free again.
    run_lease_until = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("source_type", "source_instance", "source_key", name="uq_work_items_source_key"),
        Index("ix_work_items_project_state", "project_id", "work_state"),
        Index("ix_work_items_source_project_key", "source_project_key"),
        Index("ix_work_items_source_status", "source_type", "source_status"),
        Index("ix_work_items_sync_config_id", "sync_config_id"),
        Index("ix_work_items_sync_state", "sync_state"),
        Index("ix_work_items_source_key", "source_key"),
        Index("ix_work_items_updated", "updated_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    sync_config_id = Column(String(36), ForeignKey("work_item_sync_configs.id"), nullable=True)
    source_type = Column(String(50), nullable=False, default="jira", index=True)
    source_instance = Column(String(220), nullable=False, default="default")
    source_id = Column(String(220), nullable=True)
    source_project_key = Column(String(120), nullable=True)
    source_key = Column(String(220), nullable=False)
    source_url = Column(Text, nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    issue_type = Column(String(120), nullable=True, index=True)
    source_status = Column(String(120), nullable=True)
    priority = Column(String(120), nullable=True)
    assignee = Column(String(220), nullable=True, index=True)
    reporter = Column(String(220), nullable=True)
    watchers_json = Column(JSON, default=list, nullable=False)
    labels_json = Column(JSON, default=list, nullable=False)
    components_json = Column(JSON, default=list, nullable=False)
    # Workflow run limits for this item: loop_limit, budget.
    run_limits = Column(JSON, nullable=True)
    # The work item's tasks with their status (one work item, one branch; tasks inside it, each with
    # a status): ``[{id, text, proof, status, note, run_id, updated_at}]`` (``workflow_runs/task_status``).
    task_list = Column(JSON, nullable=True)
    fix_versions_json = Column(JSON, default=list, nullable=False)
    sprint_json = Column(JSON, default=dict, nullable=False)
    board_json = Column(JSON, default=dict, nullable=False)
    parent_key = Column(String(220), nullable=True)
    epic_key = Column(String(220), nullable=True)
    linked_issues_json = Column(JSON, default=list, nullable=False)
    source_fields_json = Column(JSON, default=dict, nullable=False)
    work_state = Column(String(80), nullable=False, default="intake", index=True)
    sync_state = Column(String(80), nullable=False, default="imported")
    source_created_at = Column(DateTime, nullable=True)
    last_source_updated_at = Column(DateTime, nullable=True)
    imported_at = Column(DateTime, default=utc_now, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    sync_config = relationship("WorkItemSyncConfig")


class WorkItemSyncRun(Base):
    __tablename__ = "work_item_sync_runs"
    __table_args__ = (
        Index("ix_work_item_sync_runs_config_created", "sync_config_id", "created_at"),
        Index("ix_work_item_sync_runs_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    sync_config_id = Column(String(36), ForeignKey("work_item_sync_configs.id"), nullable=False, index=True)
    triggered_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    mode = Column(String(30), nullable=False, default="dry_run")
    status = Column(String(50), nullable=False, default="running")
    limit = Column(String(30), nullable=True)
    query_preview = Column(Text, nullable=True)
    summary_json = Column(JSON, default=dict, nullable=False)
    sample_items_json = Column(JSON, default=list, nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    sync_config = relationship("WorkItemSyncConfig")
    user = relationship("User")


class WorkItemWorkflowDefinition(Base):
    __tablename__ = "work_item_workflow_definitions"
    __table_args__ = (
        Index("ix_work_item_workflows_project_active", "project_id", "is_active"),
        Index("ix_work_item_workflows_default", "is_default", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    states_json = Column(JSON, default=list, nullable=False)
    mappings_json = Column(JSON, default=dict, nullable=False)
    sync_policy_json = Column(JSON, default=dict, nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkItemStateEvent(Base):
    __tablename__ = "work_item_state_events"
    __table_args__ = (
        Index("ix_work_item_state_events_item_created", "work_item_id", "created_at"),
        Index("ix_work_item_state_events_workflow", "workflow_id"),
        Index("ix_work_item_state_events_actor", "actor_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    workflow_id = Column(String(36), ForeignKey("work_item_workflow_definitions.id"), nullable=True)
    from_state = Column(String(80), nullable=True)
    to_state = Column(String(80), nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=True)
    source = Column(String(80), nullable=False, default="manual")
    dry_run = Column(Boolean, nullable=False, default=False)
    jira_sync_preview_json = Column(JSON, default=dict, nullable=False)
    conflict_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    workflow = relationship("WorkItemWorkflowDefinition")
    actor = relationship("User")


class WorkRepositoryProfile(Base):
    __tablename__ = "work_repository_profiles"
    __table_args__ = (
        Index("ix_work_repository_profiles_project_active", "project_id", "is_active"),
        Index("ix_work_repository_profiles_provider", "provider"),
        Index("ix_work_repository_profiles_code_repository", "code_repository_id"),
        Index("ix_work_repository_profiles_technology_baseline", "technology_baseline_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    code_repository_id = Column(String(36), ForeignKey("code_repositories.id"), nullable=True)
    technology_baseline_id = Column(String(36), nullable=True)
    name = Column(String(220), nullable=False)
    provider = Column(String(50), nullable=False, default="bitbucket")
    repository_url = Column(Text, nullable=True)
    default_branch = Column(String(120), nullable=True)
    protected_branches_json = Column(JSON, default=list, nullable=False)
    jira_project_keys_json = Column(JSON, default=list, nullable=False)
    service_description = Column(Text, nullable=True)
    owners_json = Column(JSON, default=list, nullable=False)
    default_reviewers_json = Column(JSON, default=list, nullable=False)
    branch_naming_rule = Column(String(220), nullable=False, default="{type}/{key}-{slug}")
    pr_target_branch = Column(String(120), nullable=True)
    required_pipelines_json = Column(JSON, default=list, nullable=False)
    required_tests_json = Column(JSON, default=list, nullable=False)
    setup_commands_json = Column(JSON, default=list, nullable=False)
    build_commands_json = Column(JSON, default=list, nullable=False)
    test_commands_json = Column(JSON, default=list, nullable=False)
    lint_commands_json = Column(JSON, default=list, nullable=False)
    format_commands_json = Column(JSON, default=list, nullable=False)
    package_commands_json = Column(JSON, default=list, nullable=False)
    local_run_commands_json = Column(JSON, default=list, nullable=False)
    cleanup_commands_json = Column(JSON, default=list, nullable=False)
    builder_runtime_image = Column(Text, nullable=True)
    local_toolchain_json = Column(JSON, default=list, nullable=False)
    required_env_vars_json = Column(JSON, default=list, nullable=False)
    secret_references_json = Column(JSON, default=list, nullable=False)
    protected_paths_json = Column(JSON, default=list, nullable=False)
    hotspot_files_json = Column(JSON, default=list, nullable=False)
    artifact_paths_json = Column(JSON, default=list, nullable=False)
    coverage_report_paths_json = Column(JSON, default=list, nullable=False)
    test_report_paths_json = Column(JSON, default=list, nullable=False)
    multi_repo_dependencies_json = Column(JSON, default=list, nullable=False)
    risk_tags_json = Column(JSON, default=list, nullable=False)
    important_paths_json = Column(JSON, default=list, nullable=False)
    profile_source = Column(String(80), nullable=False, default="manual")
    review_status = Column(String(80), nullable=False, default="needs_review")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    code_repository = relationship("CodeRepository")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkTechnologyBaseline(Base):
    __tablename__ = "work_technology_baselines"
    __table_args__ = (
        Index("ix_work_technology_baselines_project_active", "project_id", "is_active"),
        Index("ix_work_technology_baselines_repository_profile", "repository_profile_id"),
        Index("ix_work_technology_baselines_scope_active", "scope_level", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    scope_level = Column(String(40), nullable=False, default="global")
    technology_rules_json = Column(JSON, default=list, nullable=False)
    dependency_policy_json = Column(JSON, default=dict, nullable=False)
    eol_policy_json = Column(JSON, default=dict, nullable=False)
    compact_summary = Column(Text, nullable=True)
    review_status = Column(String(80), nullable=False, default="needs_review")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    repository_profile = relationship("WorkRepositoryProfile", foreign_keys=[repository_profile_id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingPipelineConfig(Base):
    __tablename__ = "work_coding_pipeline_configs"
    __table_args__ = (
        Index("ix_work_coding_pipeline_configs_project_active", "project_id", "is_active"),
        Index("ix_work_coding_pipeline_configs_review_status", "review_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    scope_json = Column(JSON, default=dict, nullable=False)
    stages_json = Column(JSON, default=list, nullable=False)
    required_stage_keys_json = Column(JSON, default=list, nullable=False)
    controls_json = Column(JSON, default=dict, nullable=False)
    review_status = Column(String(80), nullable=False, default="needs_review")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingPipelineRun(Base):
    __tablename__ = "work_coding_pipeline_runs"
    __table_args__ = (
        Index("ix_work_coding_pipeline_runs_item_created", "work_item_id", "started_at"),
        Index("ix_work_coding_pipeline_runs_config", "config_id"),
        Index("ix_work_coding_pipeline_runs_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    config_id = Column(String(36), ForeignKey("work_coding_pipeline_configs.id"), nullable=True)
    status = Column(String(80), nullable=False, default="running")
    current_stage_key = Column(String(120), nullable=True)
    control_state = Column(String(80), nullable=False, default="running")
    summary_json = Column(JSON, default=dict, nullable=False)
    recovery_state_json = Column(JSON, default=dict, nullable=False)
    started_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    work_item = relationship("WorkItem")
    config = relationship("WorkCodingPipelineConfig")
    starter = relationship("User", foreign_keys=[started_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingPipelineStage(Base):
    __tablename__ = "work_coding_pipeline_stages"
    __table_args__ = (
        Index("ix_work_coding_pipeline_stages_run_order", "run_id", "stage_order"),
        Index("ix_work_coding_pipeline_stages_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("work_coding_pipeline_runs.id"), nullable=False, index=True)
    stage_key = Column(String(120), nullable=False)
    label = Column(String(220), nullable=False)
    stage_order = Column(Integer, nullable=False, default=0)
    status = Column(String(80), nullable=False, default="pending")
    required = Column(Boolean, nullable=False, default=True)
    inputs_json = Column(JSON, default=dict, nullable=False)
    outputs_json = Column(JSON, default=dict, nullable=False)
    evidence_json = Column(JSON, default=list, nullable=False)
    required_actions_json = Column(JSON, default=list, nullable=False)
    policy_refs_json = Column(JSON, default=list, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    run = relationship("WorkCodingPipelineRun")
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingWorkspace(Base):
    __tablename__ = "work_coding_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_run_id",
            "change_unit_id",
            "restart_generation",
            name="uq_work_coding_workspace_run_unit_generation",
        ),
        Index("ix_work_coding_workspaces_item_created", "work_item_id", "created_at"),
        Index("ix_work_coding_workspaces_pipeline_run", "pipeline_run_id"),
        Index("ix_work_coding_workspaces_change_unit", "change_unit_id"),
        Index("ix_work_coding_workspaces_status", "status"),
        Index("ix_work_coding_workspaces_branch", "repository_slug", "feature_branch"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    pipeline_run_id = Column(String(36), ForeignKey("work_coding_pipeline_runs.id"), nullable=False, index=True)
    change_unit_id = Column(String(36), ForeignKey("work_item_change_units.id"), nullable=False, index=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    provider = Column(String(50), nullable=False, default="bitbucket")
    provider_instance = Column(String(220), nullable=False, default="default")
    project_key = Column(String(120), nullable=True)
    repository_name = Column(String(220), nullable=False)
    repository_slug = Column(String(220), nullable=False)
    repository_url = Column(Text, nullable=True)
    base_branch = Column(String(260), nullable=True)
    resolved_base_branch = Column(String(260), nullable=True)
    feature_branch = Column(String(260), nullable=False)
    base_commit = Column(String(80), nullable=True)
    workspace_path = Column(Text, nullable=False)
    source_repository_root = Column(Text, nullable=True)
    source_evidence_cutoff = Column(DateTime, nullable=True)
    restart_generation = Column(Integer, nullable=False, default=0)
    status = Column(String(80), nullable=False, default="prepared")
    evidence_json = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    pipeline_run = relationship("WorkCodingPipelineRun")
    change_unit = relationship("WorkItemChangeUnit")
    repository_profile = relationship("WorkRepositoryProfile")
    session = relationship("Session")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingReviewEvent(Base):
    __tablename__ = "work_coding_review_events"
    __table_args__ = (
        Index("ix_work_coding_review_events_item_created", "work_item_id", "created_at"),
        Index("ix_work_coding_review_events_change_unit", "change_unit_id"),
        Index("ix_work_coding_review_events_file", "work_item_id", "file_path"),
        Index("ix_work_coding_review_events_type", "event_type"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    change_unit_id = Column(String(36), ForeignKey("work_item_change_units.id"), nullable=True)
    event_type = Column(String(80), nullable=False)
    file_path = Column(Text, nullable=False)
    line_number = Column(Integer, nullable=True)
    severity = Column(String(40), nullable=True)
    status = Column(String(80), nullable=False, default="open")
    body = Column(Text, nullable=False)
    original_content = Column(Text, nullable=True)
    updated_content = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    agent_context_json = Column(JSON, default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    change_unit = relationship("WorkItemChangeUnit")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCodingAuditEvent(Base):
    __tablename__ = "work_coding_audit_events"
    __table_args__ = (
        Index("ix_work_coding_audit_events_item_created", "work_item_id", "created_at"),
        Index("ix_work_coding_audit_events_type", "event_type"),
        Index("ix_work_coding_audit_events_pipeline_run", "pipeline_run_id"),
        Index("ix_work_coding_audit_events_pr", "pr_url"),
        Index("ix_work_coding_audit_events_commit", "commit_sha"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    pipeline_run_id = Column(String(36), ForeignKey("work_coding_pipeline_runs.id"), nullable=True)
    pipeline_stage_id = Column(String(36), ForeignKey("work_coding_pipeline_stages.id"), nullable=True)
    review_event_id = Column(String(36), ForeignKey("work_coding_review_events.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    title = Column(String(300), nullable=False)
    summary = Column(Text, nullable=True)
    actor_kind = Column(String(40), nullable=False, default="user")
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    repository_name = Column(String(220), nullable=True)
    branch_name = Column(String(260), nullable=True)
    commit_sha = Column(String(80), nullable=True)
    pr_url = Column(Text, nullable=True)
    evidence_json = Column(JSON, default=dict, nullable=False)
    gate_results_json = Column(JSON, default=list, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    pipeline_run = relationship("WorkCodingPipelineRun")
    pipeline_stage = relationship("WorkCodingPipelineStage")
    review_event = relationship("WorkCodingReviewEvent")
    actor = relationship("User", foreign_keys=[actor_id])


class WorkCicdProviderConfig(Base):
    __tablename__ = "work_cicd_provider_configs"
    __table_args__ = (
        Index("ix_work_cicd_provider_configs_project_active", "project_id", "is_active"),
        Index("ix_work_cicd_provider_configs_provider", "provider_type"),
        Index("ix_work_cicd_provider_configs_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    provider_type = Column(String(50), nullable=False, default="jenkins")
    base_url = Column(Text, nullable=False)
    credential_ref = Column(String(260), nullable=True)
    allowed_actions_json = Column(JSON, default=list, nullable=False)
    job_scopes_json = Column(JSON, default=list, nullable=False)
    polling_json = Column(JSON, default=dict, nullable=False)
    webhook_json = Column(JSON, default=dict, nullable=False)
    repository_mapping_json = Column(JSON, default=dict, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    status = Column(String(80), nullable=False, default="untested")
    last_test_status = Column(String(80), nullable=True)
    last_test_summary_json = Column(JSON, default=dict, nullable=False)
    last_test_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCicdBuild(Base):
    __tablename__ = "work_cicd_builds"
    __table_args__ = (
        Index("ix_work_cicd_builds_work_item_created", "work_item_id", "created_at"),
        Index("ix_work_cicd_builds_provider_job", "provider_config_id", "job_name"),
        Index("ix_work_cicd_builds_status", "status"),
        Index("ix_work_cicd_builds_commit", "commit_sha"),
        Index("ix_work_cicd_builds_pr", "pr_url"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_config_id = Column(String(36), ForeignKey("work_cicd_provider_configs.id"), nullable=False, index=True)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=True, index=True)
    pipeline_run_id = Column(String(36), ForeignKey("work_coding_pipeline_runs.id"), nullable=True)
    pipeline_stage_id = Column(String(36), ForeignKey("work_coding_pipeline_stages.id"), nullable=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    job_name = Column(String(500), nullable=False)
    job_url = Column(Text, nullable=True)
    build_number = Column(String(80), nullable=True)
    build_url = Column(Text, nullable=True)
    status = Column(String(80), nullable=False, default="unknown")
    result = Column(String(80), nullable=True)
    branch_name = Column(String(260), nullable=True)
    commit_sha = Column(String(80), nullable=True)
    pr_url = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    triggered_by = Column(String(220), nullable=True)
    cause = Column(Text, nullable=True)
    logs_ref = Column(Text, nullable=True)
    artifacts_json = Column(JSON, default=list, nullable=False)
    test_report_json = Column(JSON, default=dict, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    provider_config = relationship("WorkCicdProviderConfig")
    work_item = relationship("WorkItem")
    pipeline_run = relationship("WorkCodingPipelineRun")
    pipeline_stage = relationship("WorkCodingPipelineStage")
    repository_profile = relationship("WorkRepositoryProfile")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCicdPipelineTrace(Base):
    __tablename__ = "work_cicd_pipeline_traces"
    __table_args__ = (
        Index("ix_work_cicd_pipeline_traces_work_item_created", "work_item_id", "created_at"),
        Index("ix_work_cicd_pipeline_traces_build", "cicd_build_id"),
        Index("ix_work_cicd_pipeline_traces_provider_job", "provider_config_id", "job_name"),
        Index("ix_work_cicd_pipeline_traces_status", "status"),
        Index("ix_work_cicd_pipeline_traces_commit", "commit_sha"),
        Index("ix_work_cicd_pipeline_traces_pr", "pr_url"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_config_id = Column(String(36), ForeignKey("work_cicd_provider_configs.id"), nullable=True, index=True)
    cicd_build_id = Column(String(36), ForeignKey("work_cicd_builds.id"), nullable=True, index=True)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    job_name = Column(String(500), nullable=False)
    job_url = Column(Text, nullable=True)
    build_number = Column(String(80), nullable=True)
    build_url = Column(Text, nullable=True)
    provider_type = Column(String(50), nullable=False, default="generic")
    branch_name = Column(String(260), nullable=True)
    commit_sha = Column(String(80), nullable=True)
    pr_url = Column(Text, nullable=True)
    status = Column(String(80), nullable=False, default="unknown")
    result = Column(String(80), nullable=True)
    triggered_by = Column(String(220), nullable=True)
    trigger_actor = Column(String(220), nullable=True)
    deployment_target = Column(String(260), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    stages_json = Column(JSON, default=list, nullable=False)
    log_excerpt_json = Column(JSON, default=dict, nullable=False)
    artifacts_json = Column(JSON, default=list, nullable=False)
    test_reports_json = Column(JSON, default=list, nullable=False)
    coverage_json = Column(JSON, default=dict, nullable=False)
    scan_reports_json = Column(JSON, default=list, nullable=False)
    failure_summary_json = Column(JSON, default=dict, nullable=False)
    agent_context_json = Column(JSON, default=dict, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    provider_config = relationship("WorkCicdProviderConfig")
    cicd_build = relationship("WorkCicdBuild")
    work_item = relationship("WorkItem")
    repository_profile = relationship("WorkRepositoryProfile")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCicdFinding(Base):
    __tablename__ = "work_cicd_findings"
    __table_args__ = (
        Index("ix_work_cicd_findings_item_created", "work_item_id", "created_at"),
        Index("ix_work_cicd_findings_provider", "provider_config_id"),
        Index("ix_work_cicd_findings_build", "cicd_build_id"),
        Index("ix_work_cicd_findings_trace", "pipeline_trace_id"),
        Index("ix_work_cicd_findings_status", "status"),
        Index("ix_work_cicd_findings_event_status", "event_status"),
        Index("ix_work_cicd_findings_commit", "commit_sha"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    provider_config_id = Column(String(36), ForeignKey("work_cicd_provider_configs.id"), nullable=True, index=True)
    cicd_build_id = Column(String(36), ForeignKey("work_cicd_builds.id"), nullable=True, index=True)
    pipeline_trace_id = Column(String(36), ForeignKey("work_cicd_pipeline_traces.id"), nullable=True, index=True)
    finding_type = Column(String(80), nullable=False, default="status_update")
    status = Column(String(80), nullable=False, default="current")
    event_status = Column(String(80), nullable=False, default="unknown")
    severity = Column(String(40), nullable=False, default="info")
    title = Column(String(300), nullable=False)
    summary = Column(Text, nullable=True)
    job_name = Column(String(500), nullable=True)
    build_number = Column(String(80), nullable=True)
    build_url = Column(Text, nullable=True)
    branch_name = Column(String(260), nullable=True)
    commit_sha = Column(String(80), nullable=True)
    pr_url = Column(Text, nullable=True)
    current_for_commit = Column(Boolean, nullable=False, default=True)
    stale_reason = Column(Text, nullable=True)
    artifacts_json = Column(JSON, default=list, nullable=False)
    comments_json = Column(JSON, default=list, nullable=False)
    evidence_json = Column(JSON, default=dict, nullable=False)
    gate_results_json = Column(JSON, default=list, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    provider_config = relationship("WorkCicdProviderConfig")
    cicd_build = relationship("WorkCicdBuild")
    pipeline_trace = relationship("WorkCicdPipelineTrace")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCicdActionPolicy(Base):
    __tablename__ = "work_cicd_action_policies"
    __table_args__ = (
        Index("ix_work_cicd_action_policies_project_active", "project_id", "is_active"),
        Index("ix_work_cicd_action_policies_provider", "provider_config_id"),
        Index("ix_work_cicd_action_policies_effect", "effect"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    provider_config_id = Column(String(36), ForeignKey("work_cicd_provider_configs.id"), nullable=True)
    actions_json = Column(JSON, default=list, nullable=False)
    scope_json = Column(JSON, default=dict, nullable=False)
    effect = Column(String(50), nullable=False, default="review_required")
    requires_approval = Column(Boolean, nullable=False, default=True)
    approval_policy_json = Column(JSON, default=dict, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    provider_config = relationship("WorkCicdProviderConfig")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkCicdActionRequest(Base):
    __tablename__ = "work_cicd_action_requests"
    __table_args__ = (
        Index("ix_work_cicd_action_requests_item_created", "work_item_id", "created_at"),
        Index("ix_work_cicd_action_requests_provider", "provider_config_id"),
        Index("ix_work_cicd_action_requests_policy", "policy_id"),
        Index("ix_work_cicd_action_requests_status", "status"),
        Index("ix_work_cicd_action_requests_action", "action"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    provider_config_id = Column(String(36), ForeignKey("work_cicd_provider_configs.id"), nullable=False, index=True)
    policy_id = Column(String(36), ForeignKey("work_cicd_action_policies.id"), nullable=True)
    pipeline_trace_id = Column(String(36), ForeignKey("work_cicd_pipeline_traces.id"), nullable=True)
    action = Column(String(80), nullable=False)
    status = Column(String(80), nullable=False, default="requested")
    reason = Column(Text, nullable=True)
    request_json = Column(JSON, default=dict, nullable=False)
    evaluation_json = Column(JSON, default=dict, nullable=False)
    approval_json = Column(JSON, default=dict, nullable=False)
    response_json = Column(JSON, default=dict, nullable=False)
    provider_run_id = Column(String(260), nullable=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    executed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)

    work_item = relationship("WorkItem")
    provider_config = relationship("WorkCicdProviderConfig")
    policy = relationship("WorkCicdActionPolicy")
    pipeline_trace = relationship("WorkCicdPipelineTrace")
    requester = relationship("User", foreign_keys=[requested_by])
    approver = relationship("User", foreign_keys=[approved_by])
    executor = relationship("User", foreign_keys=[executed_by])


class WorkItemChangeUnit(Base):
    __tablename__ = "work_item_change_units"
    __table_args__ = (
        Index("ix_work_item_change_units_item_order", "work_item_id", "dependency_order"),
        Index("ix_work_item_change_units_profile", "repository_profile_id"),
        Index("ix_work_item_change_units_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    repository_name = Column(String(220), nullable=False)
    branch_name = Column(String(260), nullable=False)
    scope = Column(Text, nullable=True)
    expected_paths_json = Column(JSON, default=list, nullable=False)
    validation_commands_json = Column(JSON, default=list, nullable=False)
    reviewer_policy_json = Column(JSON, default=dict, nullable=False)
    pr_link = Column(Text, nullable=True)
    dependency_order = Column(String(30), nullable=False, default="0")
    status = Column(String(80), nullable=False, default="planned")
    missing_profile_fields_json = Column(JSON, default=list, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    repository_profile = relationship("WorkRepositoryProfile")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkPullRequest(Base):
    __tablename__ = "work_pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "provider",
            "provider_instance",
            "project_key",
            "repository_slug",
            "pr_id",
            name="uq_work_pull_requests_provider_pr",
        ),
        Index("ix_work_pull_requests_item_updated", "work_item_id", "source_updated_at"),
        Index("ix_work_pull_requests_change_unit", "change_unit_id"),
        Index("ix_work_pull_requests_repository_profile", "repository_profile_id"),
        Index("ix_work_pull_requests_status", "status"),
        Index("ix_work_pull_requests_build_status", "build_status"),
        Index("ix_work_pull_requests_target_branch", "target_branch"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=True, index=True)
    # The provider identity is unique per Workspace (the work item's Workspace, set when the PR is recorded), so a
    # sync never finds or overwrites another Workspace's record of the same PR.
    scope_key = Column(String(36), nullable=False)
    change_unit_id = Column(String(36), ForeignKey("work_item_change_units.id"), nullable=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    provider = Column(String(50), nullable=False, default="bitbucket")
    provider_instance = Column(String(220), nullable=False, default="default")
    project_key = Column(String(120), nullable=False, default="")
    repository_slug = Column(String(220), nullable=False)
    repository_url = Column(Text, nullable=True)
    pr_id = Column(String(120), nullable=False)
    pr_key = Column(String(160), nullable=True)
    pr_url = Column(Text, nullable=False)
    title = Column(String(500), nullable=True)
    source_branch = Column(String(260), nullable=True)
    target_branch = Column(String(260), nullable=True)
    status = Column(String(80), nullable=False, default="open")
    author_json = Column(JSON, default=dict, nullable=False)
    reviewers_json = Column(JSON, default=list, nullable=False)
    approvals_json = Column(JSON, default=list, nullable=False)
    build_status = Column(String(80), nullable=True)
    mergeability = Column(String(80), nullable=True)
    linked_jira_keys_json = Column(JSON, default=list, nullable=False)
    mismatch_json = Column(JSON, default=list, nullable=False)
    raw_summary_json = Column(JSON, default=dict, nullable=False)
    source_created_at = Column(DateTime, nullable=True)
    source_updated_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, default=utc_now, nullable=False)
    # Host refresh (pull_requests/refresh.py): null = never read from the host; ok | partial | failed.
    refresh_status = Column(String(40), nullable=True)
    refresh_error_code = Column(String(80), nullable=True)
    refresh_error = Column(Text, nullable=True)
    refresh_attempted_at = Column(DateTime, nullable=True)
    refresh_requested_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    change_unit = relationship("WorkItemChangeUnit")
    repository_profile = relationship("WorkRepositoryProfile")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkEngineeringProfile(Base):
    __tablename__ = "work_engineering_profiles"
    __table_args__ = (
        Index("ix_work_engineering_profiles_user_active", "user_id", "is_active"),
        Index("ix_work_engineering_profiles_email", "primary_email"),
        Index("ix_work_engineering_profiles_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    display_name = Column(String(220), nullable=False)
    primary_email = Column(String(255), nullable=True)
    teams_json = Column(JSON, default=list, nullable=False)
    skills_json = Column(JSON, default=list, nullable=False)
    repositories_json = Column(JSON, default=list, nullable=False)
    path_ownership_json = Column(JSON, default=list, nullable=False)
    approval_roles_json = Column(JSON, default=list, nullable=False)
    reviewer_capabilities_json = Column(JSON, default=dict, nullable=False)
    timezone = Column(String(80), nullable=True)
    location = Column(String(160), nullable=True)
    preferred_review_load = Column(Integer, nullable=False, default=3)
    current_review_load = Column(Integer, nullable=False, default=0)
    fallback_reviewers_json = Column(JSON, default=list, nullable=False)
    unavailable = Column(Boolean, nullable=False, default=False)
    unavailable_reason = Column(Text, nullable=True)
    jira_usernames_json = Column(JSON, default=list, nullable=False)
    bitbucket_usernames_json = Column(JSON, default=list, nullable=False)
    github_usernames_json = Column(JSON, default=list, nullable=False)
    gitlab_usernames_json = Column(JSON, default=list, nullable=False)
    profile_source = Column(String(80), nullable=False, default="manual")
    review_status = Column(String(80), nullable=False, default="needs_review")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class WorkReviewerOverride(Base):
    __tablename__ = "work_reviewer_overrides"
    __table_args__ = (
        Index("ix_work_reviewer_overrides_item_created", "work_item_id", "created_at"),
        Index("ix_work_reviewer_overrides_change_unit", "change_unit_id"),
        Index("ix_work_reviewer_overrides_profile", "selected_profile_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    change_unit_id = Column(String(36), ForeignKey("work_item_change_units.id"), nullable=True)
    selected_profile_id = Column(String(36), ForeignKey("work_engineering_profiles.id"), nullable=True)
    selected_reviewer = Column(String(220), nullable=False)
    reason = Column(Text, nullable=True)
    evidence_json = Column(JSON, default=dict, nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    work_item = relationship("WorkItem")
    change_unit = relationship("WorkItemChangeUnit")
    selected_profile = relationship("WorkEngineeringProfile")
    actor = relationship("User")


class WorkChangePlan(Base):
    __tablename__ = "work_change_plans"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_work_change_plans_item_version"),
        Index("ix_work_change_plans_item_status", "work_item_id", "status"),
        Index("ix_work_change_plans_workflow", "workflow_id"),
        Index("ix_work_change_plans_supersedes", "supersedes_plan_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    workflow_id = Column(String(36), ForeignKey("work_item_workflow_definitions.id"), nullable=True)
    supersedes_plan_id = Column(String(36), ForeignKey("work_change_plans.id"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(80), nullable=False, default="ready_for_review", index=True)
    title = Column(String(500), nullable=False)
    understood_request = Column(Text, nullable=True)
    assumptions_json = Column(JSON, default=list, nullable=False)
    open_questions_json = Column(JSON, default=list, nullable=False)
    affected_repositories_json = Column(JSON, default=list, nullable=False)
    change_units_json = Column(JSON, default=list, nullable=False)
    proposed_branches_json = Column(JSON, default=list, nullable=False)
    planned_files_json = Column(JSON, default=list, nullable=False)
    validation_plan_json = Column(JSON, default=list, nullable=False)
    acceptance_criteria_json = Column(JSON, default=list, nullable=False)
    security_risks_json = Column(JSON, default=list, nullable=False)
    reviewer_recommendations_json = Column(JSON, default=list, nullable=False)
    required_approvals_json = Column(JSON, default=list, nullable=False)
    expected_prs_json = Column(JSON, default=list, nullable=False)
    rollback_plan = Column(Text, nullable=True)
    trace_refs_json = Column(JSON, default=list, nullable=False)
    evidence_json = Column(JSON, default=dict, nullable=False)
    jira_sync_preview_json = Column(JSON, default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    decided_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    approved_at = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)

    work_item = relationship("WorkItem")
    workflow = relationship("WorkItemWorkflowDefinition")
    supersedes_plan = relationship("WorkChangePlan", remote_side=[id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    approver = relationship("User", foreign_keys=[approved_by])
    decider = relationship("User", foreign_keys=[decided_by])


class WorkChangePlanDecision(Base):
    __tablename__ = "work_change_plan_decisions"
    __table_args__ = (
        Index("ix_work_change_plan_decisions_plan_created", "change_plan_id", "created_at"),
        Index("ix_work_change_plan_decisions_item_created", "work_item_id", "created_at"),
        Index("ix_work_change_plan_decisions_actor", "actor_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    change_plan_id = Column(String(36), ForeignKey("work_change_plans.id"), nullable=False, index=True)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    action = Column(String(80), nullable=False)
    from_status = Column(String(80), nullable=True)
    to_status = Column(String(80), nullable=False)
    reason = Column(Text, nullable=True)
    required_changes_json = Column(JSON, default=list, nullable=False)
    jira_sync_preview_json = Column(JSON, default=dict, nullable=False)
    evidence_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    change_plan = relationship("WorkChangePlan")
    work_item = relationship("WorkItem")
    actor = relationship("User")


class WorkCodingPolicy(Base):
    __tablename__ = "work_coding_policies"
    __table_args__ = (
        Index("ix_work_coding_policies_project_active", "project_id", "is_active"),
        Index("ix_work_coding_policies_type_active", "policy_type", "is_active"),
        Index("ix_work_coding_policies_repository", "repository_profile_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    repository_profile_id = Column(String(36), ForeignKey("work_repository_profiles.id"), nullable=True)
    policy_type = Column(String(80), nullable=False, default="custom", index=True)
    severity = Column(String(40), nullable=False, default="medium")
    enforcement_mode = Column(String(40), nullable=False, default="review_required")
    scope_json = Column(JSON, default=dict, nullable=False)
    rule_json = Column(JSON, default=dict, nullable=False)
    remediation = Column(Text, nullable=True)
    exceptions_json = Column(JSON, default=list, nullable=False)
    audit_settings_json = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    repository_profile = relationship("WorkRepositoryProfile")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
