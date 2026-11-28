"""Agent selection and loading helpers for scheduler step execution."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models.project.task import Task, TaskStep


async def load_agent_for_step(
    step: TaskStep,
    task: Task,
    db: Any,
    logger: logging.Logger,
) -> tuple[dict | None, str | None, str | None]:
    from app.services.session.reply_contract import REASON_PATH_UNSUPPORTED, declares_checked_reply

    from ...services.agent_definition_execution import (
        resolve_agent_definition_for_execution,
    )
    from ...services.agent_definition_execution_outcomes import (
        AgentDefinitionExecutionError,
        require_background_execution_payload,
    )

    task_cfg = dict(task.config or {})
    task_agent_id = str(task_cfg.get("agent_definition_id") or "").strip()
    runtime_target_id = await _resolve_runtime_target_id(step, db)
    thinking_level: str | None = task_cfg.get("thinking_level")

    agent_id = _resolve_agent_id(step, task_agent_id)
    if agent_id is None:
        return None, runtime_target_id, thinking_level

    # Explicit resolution: the published revision, or the named draft mode.
    # A definition the platform cannot execute raises AgentDefinitionExecutionError,
    # which fails the step with typed state — it never runs the step without the
    # agent definition it was configured with.
    resolution = await resolve_agent_definition_for_execution(db, definition_id=agent_id)
    agent_def = require_background_execution_payload(
        resolution, logger_=logger, subject="step_executor"
    )
    if agent_def is None:
        return None, runtime_target_id, thinking_level
    if declares_checked_reply(agent_def):
        # A step's final reply is never checked against the agent's reply contract, so a
        # checked agent is refused before any model call, with the same typed step refusal.
        logger.error("[step_executor] refusing background execution: %s (definition=%s)",
                     REASON_PATH_UNSUPPORTED, resolution.definition_id)
        raise AgentDefinitionExecutionError(replace(resolution, status=REASON_PATH_UNSUPPORTED, payload=None))

    runtime_target_id = resolution.runtime_target_id or runtime_target_id
    thinking_level = resolution.thinking_level or thinking_level

    return agent_def, runtime_target_id, thinking_level


async def _resolve_runtime_target_id(step: TaskStep, db: Any) -> str | None:
    return step.runtime_selector.get("runtime_target_id")


def _resolve_agent_id(step: TaskStep, task_agent_id: str) -> str | None:
    if "agent_definition_id" in step.connector_params:
        step_agent_id = str(step.connector_params["agent_definition_id"]).strip()
        if step_agent_id == "":
            return None
        return step_agent_id or None

    return task_agent_id or None
