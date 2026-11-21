"""Admission of an Action's general agent turn before any session or model dispatch.

The general branch of ``task_execution`` runs an agent turn for a task that is not an enabled-step
or Work intake sync task. This module decides, from the stored task alone and before anything is
created, whether that turn may run:

* **Type.** Only ``agent_run`` is an agent turn.
  ``webhook_relay`` and any other type are refused (``action_type_unsupported``).
* **Raw values.** ``config`` must be an object; ``agent_definition_id`` and ``prompt`` must be
  strings when present (arrays or objects are refused, never stringified).
* **Configured agent.** Resolved with the task owner's visibility. A refusal the resolver already
  types (inactive, not published, mode not configured) stays the existing
  :class:`AgentDefinitionExecutionError`. A definition that does not resolve for the owner is
  refused (``action_agent_not_found``) instead of degrading to an agent-less turn. Its target
  Workspace must be global or the task's own (``action_agent_workspace_mismatch``).
* **Instruction.** Without an agent, a non-blank string prompt is required. With an agent, the
  configured prompt or an *authored* instruction of the agent (goal, system prompt, output prompt
  or an enabled step's instructions) is required; the boilerplate the payload serializer builds
  around empty fields does not count. Nothing is invented (``action_instruction_missing``).

Refusals carry only a fixed code: no foreign Workspace or agent identity is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import REFUSAL_STATUSES, STATUS_RESOLVED

from ...services.agent_definition_execution import resolve_agent_definition_for_execution
from ...services.agent_definition_execution_outcomes import AgentDefinitionExecutionError

AGENT_TURN_TASK_TYPES = frozenset({"agent_run"})

TYPE_UNSUPPORTED = "action_type_unsupported"
CONFIG_INVALID = "action_config_invalid"
AGENT_ID_INVALID = "action_agent_id_invalid"
PROMPT_INVALID = "action_prompt_invalid"
AGENT_NOT_FOUND = "action_agent_not_found"
AGENT_WORKSPACE_MISMATCH = "action_agent_workspace_mismatch"
INSTRUCTION_MISSING = "action_instruction_missing"
AGENT_AND_WORKFLOW = "action_agent_and_workflow"  # either a workflow run or an agent + prompt

REFUSAL_MESSAGES = {
    TYPE_UNSUPPORTED: "This Action type does not run an agent turn.",
    CONFIG_INVALID: "The Action configuration is not an object.",
    AGENT_ID_INVALID: "The configured agent reference is not a text value.",
    PROMPT_INVALID: "The configured instruction is not a text value.",
    AGENT_NOT_FOUND: "The configured agent is not available to the Action's owner.",
    AGENT_WORKSPACE_MISMATCH: "The configured agent belongs to a different Workspace than the Action.",
    INSTRUCTION_MISSING: "The Action has no instruction and its agent has no authored instruction.",
    AGENT_AND_WORKFLOW: "An Action runs either a workflow run or an agent with a prompt, never both.",
}


class ActionAdmissionError(RuntimeError):
    """A general agent turn refused before any session or model dispatch; fixed code only."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def as_metadata(self) -> dict[str, str]:
        return {"code": self.code, "message": REFUSAL_MESSAGES[self.code]}


@dataclass(frozen=True)
class AdmittedAgentTurn:
    prompt: str
    agent_definition: dict[str, Any] | None
    runtime_target_id: str | None
    thinking_level: Any


def _optional_text(value: Any, code: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ActionAdmissionError(code)
    return value.strip()


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_authored_instruction(payload: dict[str, Any]) -> bool:
    """Whether the agent itself carries an instruction a person wrote (not serializer boilerplate)."""
    if any(_nonblank(payload.get(key)) for key in ("goal", "systemPrompt", "outputPrompt")):
        return True
    return any(
        isinstance(step, dict) and step.get("isEnabled") and _nonblank(step.get("instructions"))
        for step in payload.get("steps") or []
    )


async def admit_agent_turn(db: AsyncSession, task: Any) -> AdmittedAgentTurn:
    """The admitted turn, or :class:`ActionAdmissionError` / :class:`AgentDefinitionExecutionError`."""
    if task.task_type not in AGENT_TURN_TASK_TYPES:
        raise ActionAdmissionError(TYPE_UNSUPPORTED)
    config = task.config if task.config is not None else {}
    if not isinstance(config, dict):
        raise ActionAdmissionError(CONFIG_INVALID)
    agent_definition_id = _optional_text(config.get("agent_definition_id"), AGENT_ID_INVALID)
    if agent_definition_id and config.get("workflow_run"):
        raise ActionAdmissionError(AGENT_AND_WORKFLOW)
    # Checked stripped; executed as configured (unchanged text for known healthy prompt runs).
    prompt = config.get("prompt") if _optional_text(config.get("prompt"), PROMPT_INVALID) else ""
    thinking_level = config.get("thinking_level")

    if not agent_definition_id:
        if not prompt:
            raise ActionAdmissionError(INSTRUCTION_MISSING)
        return AdmittedAgentTurn(prompt=prompt, agent_definition=None, runtime_target_id=None,
                                 thinking_level=thinking_level)

    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=agent_definition_id, visible_to_user_id=task.owner_id
    )
    if resolution.status in REFUSAL_STATUSES:
        # Inactive, not published or mode not configured: the existing typed refusal.
        raise AgentDefinitionExecutionError(resolution)
    payload = resolution.payload
    if resolution.status != STATUS_RESOLVED or not isinstance(payload, dict):
        raise ActionAdmissionError(AGENT_NOT_FOUND)
    target_workspace = str(payload.get("projectId") or "").strip()
    if target_workspace and target_workspace != str(task.project_id or "").strip():
        raise ActionAdmissionError(AGENT_WORKSPACE_MISMATCH)
    if not prompt:
        if not has_authored_instruction(payload) or not _nonblank(payload.get("prompt")):
            raise ActionAdmissionError(INSTRUCTION_MISSING)
        prompt = payload["prompt"]
    return AdmittedAgentTurn(
        prompt=prompt,
        agent_definition=payload,
        runtime_target_id=resolution.runtime_target_id or None,
        thinking_level=resolution.thinking_level or thinking_level,
    )


__all__ = [
    "AGENT_TURN_TASK_TYPES",
    "ActionAdmissionError",
    "AdmittedAgentTurn",
    "admit_agent_turn",
    "has_authored_instruction",
]
