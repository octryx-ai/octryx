from pydantic import ValidationError

from app.schemas.admin.admin_task_panel import (
    SchedulerCreateRequest,
    TaskCreateRequest,
    TaskDependencyUpsertRequest,
    TaskStepCreateRequest,
)


def test_task_request_defaults_and_validation_remain_stable():
    task_payload = TaskCreateRequest(name="Nightly sync", dispatch_binding="agent_definition")
    step_payload = TaskStepCreateRequest()
    dependency_payload = TaskDependencyUpsertRequest(depends_on_task_id="task-1")
    scheduler_payload = SchedulerCreateRequest(
        name="Hourly run",
        cron_expression="0 * * * *",
        task_id="task-1",
    )

    assert task_payload.task_type == "agent_run"
    assert task_payload.agent_type == "diagnosis"
    assert task_payload.config == {}
    try:
        TaskCreateRequest(name="Unbound")
    except ValidationError as exc:
        assert "dispatch_binding" in str(exc)
    else:
        raise AssertionError("a create without a dispatch binding must be refused")
    assert step_payload.name == "Step"
    assert step_payload.runtime_selector == {}
    assert step_payload.allowed_tools == []
    assert dependency_payload.condition == "success"
    assert scheduler_payload.is_active is True

    try:
        TaskCreateRequest(name="Invalid Task", max_concurrent_agents=0, dispatch_binding="agent_definition")
    except ValidationError as exc:
        assert "max_concurrent_agents" in str(exc)
    else:
        raise AssertionError("Expected task validation to reject zero concurrency")
