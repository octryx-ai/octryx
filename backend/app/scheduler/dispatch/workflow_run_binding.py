"""Explicit phased-workflow Action admission before any session exists.

NULL never implies this binding. The existing Action execution and webhook service-principal
path remain responsible for the turn; this validates that local queue dispatch cannot degrade
into an ordinary prompt or device run after the stored Action changes.
"""
from __future__ import annotations

from typing import Any

from ...services.run_admission import denials
from ...services.run_admission.denials import STATE_NEEDS_CONFIGURATION, WORKSPACE_REQUIRED
from ..execution.action_admission import ActionAdmissionError

MESSAGES = {
    "dispatch_binding_type_unsupported": "A workflow-bound Action must be an agent run.",
    "dispatch_binding_steps_enabled": "A workflow-bound Action cannot have enabled steps.",
    "dispatch_binding_workflow_required": "A workflow-bound Action must name a phased workflow.",
    "dispatch_binding_server_required": "A workflow-bound Action must explicitly select the server runtime.",
    "dispatch_binding_agent_forbidden": "A workflow-bound Action cannot also select an agent.",
    "dispatch_binding_workflow_unavailable": "The phased workflow is not published in the Action's Workspace.",
    "dispatch_binding_owner_unavailable": "The Action needs an active owner and Workspace in its owner's scope.",
    WORKSPACE_REQUIRED: denials.MESSAGES[WORKSPACE_REQUIRED],
    "action_config_invalid": "The Action configuration is not an object.",
    "action_instruction_missing": "A workflow-bound Action needs an authored instruction.",
}


class WorkflowDispatchBindingError(ActionAdmissionError):
    def as_metadata(self) -> dict[str, str]:
        """The fixed code and message; a missing Workspace is typed like every run start's refusal."""
        typed = {"state": STATE_NEEDS_CONFIGURATION, "reason": WORKSPACE_REQUIRED} if self.code == WORKSPACE_REQUIRED \
            else {}
        return {"code": self.code, "message": MESSAGES[self.code], **typed}


def _refuse(code: str) -> None:
    raise WorkflowDispatchBindingError(code)


async def require_workflow_bound_state(db: Any, task: Any, *, has_steps: bool) -> None:
    """Check the explicit binding's complete effective state without creating anything."""
    from ...models import Project, User
    from ...services.workflow_runs.access import require_start_scope
    from ...services.workflow_runs.engine import published_phased_flow
    from ...services.workflow_runs.records import WorkflowRunError

    if task.task_type != "agent_run":
        _refuse("dispatch_binding_type_unsupported")
    if has_steps:
        _refuse("dispatch_binding_steps_enabled")
    config = task.config
    if not isinstance(config, dict):
        _refuse("action_config_invalid")
    if config.get("agent_definition_id") is not None and config.get("agent_definition_id") != "":
        _refuse("dispatch_binding_agent_forbidden")
    if not isinstance(config.get("prompt"), str) or not config["prompt"].strip():
        _refuse("action_instruction_missing")
    workflow = config.get("workflow_run")
    if not isinstance(workflow, dict):
        _refuse("dispatch_binding_workflow_required")
    key = workflow.get("workflow_key")
    if not isinstance(key, str) or not key.strip() or len(key.strip()) > 180:
        _refuse("dispatch_binding_workflow_required")
    runtime = workflow.get("runtime_target")
    if not isinstance(runtime, dict) or runtime.get("kind") != "server":
        _refuse("dispatch_binding_server_required")
    if not task.project_id:
        _refuse(WORKSPACE_REQUIRED)  # a workflow run starts only in a Workspace (typed, as at every run start)
    project = await db.get(Project, task.project_id)
    owner = await db.get(User, task.owner_id) if task.owner_id else None
    if project is None or not project.is_active or owner is None or not owner.is_active:
        _refuse("dispatch_binding_owner_unavailable")
    try:
        await require_start_scope(db, owner, project_id=project.id, item=None)
    except WorkflowRunError:
        _refuse("dispatch_binding_owner_unavailable")
    if await published_phased_flow(db, key.strip(), project.id) is None:
        _refuse("dispatch_binding_workflow_unavailable")
