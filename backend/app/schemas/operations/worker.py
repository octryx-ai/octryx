from typing import Any

from pydantic import BaseModel, Field

from ..core.workspace_ref import WorkspaceId


class WorkerCreateRequest(BaseModel):
    project_id: WorkspaceId = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    avatar_url: str | None = Field(default=None, max_length=500)
    schedule_type: str = Field(default="always_on", min_length=1, max_length=30)
    timezone: str = Field(default="UTC", min_length=1, max_length=50)
    work_hours_start: str | None = Field(default=None, max_length=5)
    work_hours_end: str | None = Field(default=None, max_length=5)
    on_call_schedule: dict[str, Any] | list[Any] | None = None
    autonomy_level: str = Field(default="supervised", min_length=1, max_length=20)
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    report_channel: str | None = Field(default=None, max_length=100)
    escalation_user_id: str | None = Field(default=None, max_length=36)
    report_schedule: str | None = Field(default=None, max_length=50)
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    max_parallel_tasks: int = Field(default=3, ge=1, le=20)
    knowledge_categories_required: list[str] | None = None
    warmup_period_hours: int = Field(default=24, ge=0, le=720)


class WorkerPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    avatar_url: str | None = Field(default=None, max_length=500)
    schedule_type: str | None = Field(default=None, min_length=1, max_length=30)
    timezone: str | None = Field(default=None, min_length=1, max_length=50)
    work_hours_start: str | None = Field(default=None, max_length=5)
    work_hours_end: str | None = Field(default=None, max_length=5)
    on_call_schedule: dict[str, Any] | list[Any] | None = None
    autonomy_level: str | None = Field(default=None, min_length=1, max_length=20)
    allowed_actions: list[str] | None = None
    forbidden_actions: list[str] | None = None
    report_channel: str | None = Field(default=None, max_length=100)
    escalation_user_id: str | None = Field(default=None, max_length=36)
    report_schedule: str | None = Field(default=None, max_length=50)
    trust_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_active: bool | None = None
    knowledge_categories_required: list[str] | None = None
    warmup_period_hours: int | None = Field(default=None, ge=0, le=720)
    current_incident_id: str | None = Field(default=None, max_length=36)
    current_session_id: str | None = Field(default=None, max_length=36)
    current_priority: str | None = Field(default=None, min_length=1, max_length=20)
    active_tasks_count: int | None = Field(default=None, ge=0, le=1000)
    max_parallel_tasks: int | None = Field(default=None, ge=1, le=20)
    system_health_summary: dict[str, Any] | None = None
    tasks_completed_today: int | None = Field(default=None, ge=0)
    incidents_resolved_today: int | None = Field(default=None, ge=0)
    escalations_today: int | None = Field(default=None, ge=0)
    llm_cost_today: float | None = Field(default=None, ge=0.0)
    status: str | None = Field(default=None, min_length=1, max_length=20)
    heartbeat: bool | None = None


class WorkerResponse(BaseModel):
    id: str
    project_id: str
    name: str
    role: str
    description: str | None
    avatar_url: str | None
    schedule_type: str
    timezone: str
    work_hours_start: str | None
    work_hours_end: str | None
    on_call_schedule: dict[str, Any] | list[Any] | None
    autonomy_level: str
    effective_autonomy_level: str
    allowed_actions: list[str]
    forbidden_actions: list[str]
    report_channel: str | None
    escalation_user_id: str | None
    report_schedule: str | None
    trust_score: float
    effective_action_permissions: dict[str, bool]
    total_tasks_completed: int
    total_incidents_resolved: int
    avg_resolution_time_minutes: float | None
    is_active: bool
    created_at: str | None
    onboarding: dict[str, Any]
    runtime_state: dict[str, Any]


class WorkerMonitorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    monitor_type: str = Field(min_length=1, max_length=50)
    check_interval_minutes: int = Field(default=15, ge=1, le=1440)
    check_query: str | None = Field(default=None, max_length=4000)
    threshold_config: dict[str, Any] = Field(default_factory=dict)
    action_on_warning: str | None = Field(default=None, max_length=50)
    action_on_critical: str | None = Field(default=None, max_length=50)
    baseline_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class WorkerMonitorPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    monitor_type: str | None = Field(default=None, min_length=1, max_length=50)
    check_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    check_query: str | None = Field(default=None, max_length=4000)
    threshold_config: dict[str, Any] | None = None
    action_on_warning: str | None = Field(default=None, max_length=50)
    action_on_critical: str | None = Field(default=None, max_length=50)
    baseline_json: dict[str, Any] | None = None
    is_active: bool | None = None


class WorkerMonitorResponse(BaseModel):
    id: str
    worker_id: str
    name: str
    monitor_type: str
    check_interval_minutes: int
    check_query: str | None
    threshold_config: dict[str, Any]
    action_on_warning: str | None
    action_on_critical: str | None
    baseline_json: dict[str, Any]
    last_check_at: str | None
    last_status: str | None
    consecutive_failures: int
    is_active: bool
    created_at: str | None
    updated_at: str | None


class WorkerMonitorEventResponse(BaseModel):
    id: str
    monitor_id: str
    worker_id: str
    severity: str
    detected_value: str | None
    threshold_value: str | None
    triggered_action: str | None
    session_id: str | None
    task_run_id: str | None
    resolved_at: str | None
    resolution_summary: str | None
    created_at: str | None


class WorkerTrustEventCreateRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    task_run_id: str | None = Field(default=None, max_length=36)
    reason: str | None = Field(default=None, max_length=4000)
    trust_delta: float | None = Field(default=None, ge=-1.0, le=1.0)


class WorkerTrustEventResponse(BaseModel):
    id: str
    worker_id: str
    event_type: str
    task_run_id: str | None
    trust_delta: float
    new_trust_score: float
    reason: str | None
    created_at: str | None


class WorkerShiftStartRequest(BaseModel):
    shift_type: str = Field(default="morning", min_length=1, max_length=20)


class WorkerShiftHandoverRequest(BaseModel):
    handover_summary: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="handed_over", min_length=1, max_length=20)


class WorkerShiftResponse(BaseModel):
    id: str
    worker_id: str
    shift_start: str | None
    shift_end: str | None
    shift_type: str
    handover_summary: str | None
    open_items: list[dict[str, Any]]
    completed_items: list[dict[str, Any]]
    escalations_count: int
    autonomous_actions_count: int
    status: str
    created_at: str | None


class WorkerDailyAgendaResponse(BaseModel):
    id: str
    worker_id: str
    date: str
    agenda_items: list[dict[str, Any]]
    generated_at: str | None
    status: str


class WorkerEscalationRuleCreateRequest(BaseModel):
    trigger_condition: str = Field(min_length=1, max_length=200)
    situation_pattern: str | None = Field(default=None, max_length=4000)
    escalate_to_user_id: str | None = Field(default=None, max_length=36)
    escalate_via: str = Field(default="slack", min_length=1, max_length=50)
    message_template: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="medium", min_length=1, max_length=20)


class WorkerEscalationRuleResponse(BaseModel):
    id: str
    worker_id: str
    trigger_condition: str
    situation_pattern: str | None
    escalate_to_user_id: str | None
    escalate_via: str
    message_template: str | None
    priority: str
    times_triggered: int
    times_resolved_after: int
    created_at: str | None


class WorkerEscalationResponse(BaseModel):
    id: str
    worker_id: str
    rule_id: str | None
    session_id: str | None
    reason: str
    context_summary: str | None
    escalated_to: str | None
    escalation_channel: str | None
    human_response: str | None
    was_necessary: bool | None
    resolution_time_minutes: int | None
    created_at: str | None


class WorkerEscalationReviewRequest(BaseModel):
    human_response: str | None = Field(default=None, max_length=4000)
    was_necessary: bool
    resolution_time_minutes: int | None = Field(default=None, ge=0, le=10080)


class WorkerReportResponse(BaseModel):
    id: str
    worker_id: str
    report_type: str
    period_start: str
    period_end: str
    summary: str | None
    incidents_detected: int
    incidents_resolved: int
    incidents_escalated: int
    autonomous_actions_taken: int
    knowledge_entries_created: int
    memory_updates: int
    highlights: list[dict[str, Any]]
    concerns: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    delivery_status: str
    delivered_to: list[str]
    created_at: str | None


class WorkerLearningResponse(BaseModel):
    id: str
    worker_id: str
    learning_type: str
    context: str | None
    learning_content: str
    confidence: float
    times_applied: int
    times_succeeded: int
    source_session_id: str | None
    created_at: str | None


class WorkerDelegationCreateRequest(BaseModel):
    to_worker_id: str | None = Field(default=None, max_length=36)
    source_session_id: str | None = Field(default=None, max_length=36)
    task_run_id: str | None = Field(default=None, max_length=36)
    required_domain: str | None = Field(default=None, max_length=50)
    priority: int = Field(default=5, ge=0, le=10)
    requested_action: str = Field(default="diagnose", min_length=1, max_length=50)
    context_summary: str | None = Field(default=None, max_length=4000)
    context_payload: dict[str, Any] | list[Any] = Field(default_factory=dict)


class WorkerDelegationRespondRequest(BaseModel):
    action: str = Field(min_length=1, max_length=20)
    response_note: str | None = Field(default=None, max_length=4000)


class WorkerDelegationCompleteRequest(BaseModel):
    status: str = Field(default="completed", min_length=1, max_length=20)
    completion_summary: str | None = Field(default=None, max_length=4000)


class WorkerDelegationResponse(BaseModel):
    id: str
    project_id: str
    from_worker_id: str
    from_worker_name: str | None
    to_worker_id: str
    to_worker_name: str | None
    source_session_id: str | None
    delegated_session_id: str | None
    task_run_id: str | None
    required_domain: str | None
    priority: int
    requested_action: str
    context_summary: str | None
    context_payload: dict[str, Any] | list[Any]
    auto_selected: bool
    status: str
    response_note: str | None
    completion_summary: str | None
    created_at: str | None
    responded_at: str | None
    completed_at: str | None


class WorkerPoolConfigUpdateRequest(BaseModel):
    min_workers: int | None = Field(default=None, ge=1, le=100)
    max_workers: int | None = Field(default=None, ge=1, le=200)
    current_workers: int | None = Field(default=None, ge=0, le=200)
    scale_up_threshold: int | None = Field(default=None, ge=1, le=1000)
    scale_down_threshold: int | None = Field(default=None, ge=0, le=1000)
    scale_up_cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    scale_down_cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    max_llm_cost_per_hour: float | None = Field(default=None, ge=0.0, le=100000.0)
    queue_backend: str | None = Field(default=None, min_length=1, max_length=20)
    redis_url: str | None = Field(default=None, max_length=500)
    hpa_target_queue_depth: int | None = Field(default=None, ge=1, le=1000)


class WorkerPoolConfigResponse(BaseModel):
    id: str
    project_id: str
    min_workers: int
    max_workers: int
    current_workers: int
    scale_up_threshold: int
    scale_down_threshold: int
    scale_up_cooldown_minutes: int
    scale_down_cooldown_minutes: int
    max_llm_cost_per_hour: float
    last_scale_action: str | None
    last_scale_at: str | None
    queue_backend: str
    redis_url: str | None
    hpa_target_queue_depth: int
    updated_at: str | None


class WorkerRateLimitUpdateRequest(BaseModel):
    max_requests_per_minute: int | None = Field(default=None, ge=1, le=100000)
    max_tokens_per_hour: int | None = Field(default=None, ge=1, le=100000000)
    max_cost_per_hour: float | None = Field(default=None, ge=0.0, le=100000.0)
    max_cost_per_day: float | None = Field(default=None, ge=0.0, le=1000000.0)
    on_minute_limit: str | None = Field(default=None, min_length=1, max_length=20)
    on_cost_limit: str | None = Field(default=None, min_length=1, max_length=30)


class WorkerRateLimitResponse(BaseModel):
    id: str
    project_id: str
    max_requests_per_minute: int
    max_tokens_per_hour: int
    max_cost_per_hour: float
    max_cost_per_day: float
    on_minute_limit: str
    on_cost_limit: str
    current_rpm: float
    current_hour_tokens: int
    current_hour_cost: float
    current_day_cost: float
    reset_minute_at: str | None
    reset_hour_at: str | None
    reset_day_at: str | None
    updated_at: str | None


class WorkerCapacityLogResponse(BaseModel):
    id: str
    worker_id: str
    queue_depth: int
    active_tasks: int
    avg_task_duration_minutes: float | None
    llm_cost_last_hour: float
    cpu_pressure: str
    recorded_at: str | None


class WorkerDomainExpertiseUpsertRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=50)
    success: bool = True
    duration_minutes: float | None = Field(default=None, ge=0.0, le=100000.0)


class WorkerDomainExpertiseResponse(BaseModel):
    id: str
    worker_id: str
    domain: str
    expertise_level: str
    tasks_completed: int
    avg_resolution_time_minutes: float | None
    success_rate: float
    updated_at: str | None


class TaskRoutingRuleCreateRequest(BaseModel):
    priority: int = Field(default=100, ge=1, le=1000)
    condition_type: str = Field(min_length=1, max_length=50)
    condition_config: dict[str, Any] = Field(default_factory=dict)
    target_type: str = Field(default="worker_pool", min_length=1, max_length=20)
    target_config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class TaskRoutingRuleResponse(BaseModel):
    id: str
    project_id: str
    priority: int
    condition_type: str
    condition_config: dict[str, Any]
    target_type: str
    target_config: dict[str, Any]
    is_active: bool
    created_at: str | None
