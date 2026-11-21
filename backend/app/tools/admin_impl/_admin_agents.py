"""Admin tools for agent management."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.tools.context import ToolContext

from ...services.agent_definition_authoring import governed_agent_definition_write
from ...services.agent_definition_writers import AgentDefinitionWriter
from ._admin_common import _require_admin_or_operator, _resolve_agent_definition


class AdminListAgentsTool:
    name = "admin_list_agents"
    description = (
        "List all agent definitions. Admin/operator only. "
        "Returns name, type, description, active status, and step count."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from sqlalchemy import select

        from ...models import AgentDefinition
        from ...services.project.private_workspace import hidden_private_ids  # noqa: PLC0415

        hidden = await hidden_private_ids(context.db, str(context.user_id))
        result = await context.db.execute(select(AgentDefinition).order_by(AgentDefinition.name))
        agents = [agent for agent in result.scalars().all() if agent.project_id not in hidden]
        return {
            "agents": [
                {
                    "id": agent.id,
                    "name": agent.name,
                    "agent_type": agent.agent_type,
                    "description": agent.description or "",
                    "is_active": agent.is_active,
                    "thinking_level": agent.thinking_level,
                    "step_count": len(agent.steps) if hasattr(agent, "steps") and agent.steps else 0,
                    "created_at": agent.created_at.isoformat() if agent.created_at else None,
                }
                for agent in agents
            ],
            "count": len(agents),
        }


class AdminGetAgentTool:
    name = "admin_get_agent"
    description = (
        "Get full details of an agent definition including all steps. "
        "Admin/operator only. Identify by name or agent_id."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        identifier = str(params.get("name") or params.get("agent_id") or "").strip()
        if not identifier:
            return {"error": "name or agent_id is required"}

        from sqlalchemy import select

        from ...models import AgentDefinition

        result = await context.db.execute(
            select(AgentDefinition).where((AgentDefinition.name == identifier) | (AgentDefinition.id == identifier))
        )
        agent = result.scalar_one_or_none()
        from ...services.project.private_workspace import hidden_private_ids  # noqa: PLC0415

        if not agent or agent.project_id in await hidden_private_ids(context.db, str(context.user_id)):
            return {"error": f"Agent '{identifier}' not found"}

        steps = [
            {
                "position": step.position,
                "name": step.name,
                "step_type": step.step_type,
                "instructions": step.instructions,
                "success_criteria": step.success_criteria,
                "allowed_tools": step.allowed_tools,
                "is_enabled": step.is_enabled,
            }
            for step in (agent.steps or [])
        ]
        return {
            "id": agent.id,
            "name": agent.name,
            "agent_type": agent.agent_type,
            "description": agent.description,
            "goal": agent.goal,
            "system_prompt": agent.system_prompt,
            "thinking_level": agent.thinking_level,
            "is_active": agent.is_active,
            "steps": steps,
        }


def _validated_step_payloads(
    steps: list[Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Check the shape of every requested step before anything is written.

    Returns the steps unchanged plus ``None``, or an empty list plus the same error
    message the create tool has always returned for a malformed step. Separated out so
    the check can run ahead of the governed write scope; see the call site.
    """
    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            return [], f"steps[{index - 1}] must be an object"
    return list(steps), None


class AdminCreateAgentTool:
    name = "admin_create_agent"
    description = (
        "Create a new DB-backed agent definition with optional steps. Admin/operator only. "
        "Requires name. Optional: description, goal, agent_type, "
        "thinking_level, system_prompt, output_prompt, branch_prefix and steps."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        from ...models import AgentDefinition, AgentStep

        name = str(params.get("name") or "").strip()
        if not name:
            return {"error": "name is required"}

        steps = params.get("steps") or []
        if not isinstance(steps, list):
            return {"error": "steps must be a list"}

        clone_source = None
        if params.get("clone_from_agent_id") is not None or params.get("clone_from_name") is not None:
            clone_source, clone_error = await _resolve_agent_definition(
                context,
                params.get("clone_from_agent_id") or params.get("clone_from_name"),
            )
            if clone_error:
                return {"error": clone_error}
            if not steps:
                steps = [
                    {
                        "position": step.position,
                        "name": step.name,
                        "step_type": step.step_type,
                        "instructions": step.instructions,
                        "success_criteria": step.success_criteria,
                        "allowed_tools": step.allowed_tools,
                        "is_enabled": step.is_enabled,
                    }
                    for step in sorted(clone_source.steps or [], key=lambda item: item.position)
                ]

        # Every rejection of the model's arguments happens *before* the governed
        # scope opens. A ``return {"error": ...}`` from inside it exits the context
        # manager normally, so the boundary would finalize: the caller would be told
        # the create was rejected while a revision and an audit row recorded a
        # governed write of the half-built definition.
        step_payloads, step_error = _validated_step_payloads(steps)
        if step_error:
            return {"error": step_error}

        # One governed write boundary: the tool's create is snapshotted,
        # validated, and recorded as a revision with an audit entry.
        async with governed_agent_definition_write(
            context.db,
            writer=AgentDefinitionWriter.ADMIN_TOOL_CREATE,
            actor_id=str(context.user_id or ""),
        ):
            agent = AgentDefinition(
                id=str(uuid.uuid4()),
                owner_id=context.user_id,
                runtime_target_id=str(params.get("runtime_target_id") or "").strip() or None,
                name=name,
                description=str(
                    params.get("description")
                    if params.get("description") is not None
                    else (clone_source.description if clone_source else "")
                ),
                goal=str(
                    params.get("goal") if params.get("goal") is not None else (clone_source.goal if clone_source else "")
                ),
                agent_type=str(
                    params.get("agent_type")
                    if params.get("agent_type") is not None
                    else (clone_source.agent_type if clone_source else "diagnosis")
                ),
                thinking_level=str(
                    params.get("thinking_level")
                    if params.get("thinking_level") is not None
                    else (clone_source.thinking_level if clone_source else "light")
                ),
                system_prompt=str(
                    params.get("system_prompt")
                    if params.get("system_prompt") is not None
                    else (clone_source.system_prompt if clone_source else "")
                ),
                output_prompt=str(
                    params.get("output_prompt")
                    if params.get("output_prompt") is not None
                    else (clone_source.output_prompt if clone_source else "")
                ),
                branch_prefix=str(
                    params.get("branch_prefix")
                    if params.get("branch_prefix") is not None
                    else (clone_source.branch_prefix if clone_source else "codex")
                ).strip("/")
                or "codex",
                is_active=bool(params.get("is_active", True)),
                # A clone keeps its source's tool setting and reply contract.
                **(
                    {"tool_surface": clone_source.tool_surface, "reply_contract_json": clone_source.reply_contract_json}
                    if clone_source
                    else {}
                ),
            )
            context.db.add(agent)
            await context.db.flush()

            created_steps: list[dict[str, Any]] = []
            for index, raw_step in enumerate(step_payloads, start=1):
                step = AgentStep(
                    id=str(uuid.uuid4()),
                    agent_id=agent.id,
                    position=int(raw_step.get("position") or index),
                    name=str(raw_step.get("name") or f"Step {index}").strip() or f"Step {index}",
                    step_type=str(raw_step.get("step_type") or "analysis"),
                    instructions=str(raw_step.get("instructions") or ""),
                    success_criteria=str(raw_step.get("success_criteria") or ""),
                    allowed_tools_json=json.dumps(list(raw_step.get("allowed_tools") or [])),
                    is_enabled=bool(raw_step.get("is_enabled", True)),
                )
                context.db.add(step)
                created_steps.append(
                    {
                        "position": step.position,
                        "name": step.name,
                        "step_type": step.step_type,
                        "allowed_tools": json.loads(step.allowed_tools_json or "[]"),
                    }
                )

            await context.db.commit()
        return {
            "status": "created",
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "agent_type": agent.agent_type,
                "project_id": agent.project_id,
                "thinking_level": agent.thinking_level,
                "clone_source_id": clone_source.id if clone_source else None,
                "step_count": len(created_steps),
                "steps": created_steps,
            },
        }


class AdminUpdateAgentTool:
    name = "admin_update_agent"
    description = (
        "Update a DB-backed agent definition. Admin/operator only. "
        "Identify the agent by agent_id or name. Can update prompts, mode, thinking level, "
        "project assignment, runtime, branch prefix and active state."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if err := _require_admin_or_operator(context):
            return {"error": err}
        if not context.db:
            return {"error": "No database connection"}

        agent, error = await _resolve_agent_definition(
            context,
            params.get("agent_id") or params.get("name"),
        )
        if error:
            return {"error": error}

        # One governed write boundary: the tool's edit is snapshotted,
        # validated, and recorded as a revision with an audit entry.
        async with governed_agent_definition_write(
            context.db,
            writer=AgentDefinitionWriter.ADMIN_TOOL_UPDATE,
            actor_id=str(context.user_id or ""),
        ):
            changes: list[str] = []
            for field in ("name", "description", "goal", "agent_type", "thinking_level", "system_prompt", "output_prompt"):
                if params.get(field) is not None:
                    setattr(agent, field, str(params.get(field) or ""))
                    changes.append(f"{field} updated")
            if params.get("branch_prefix") is not None:
                agent.branch_prefix = str(params.get("branch_prefix") or "").strip("/") or "codex"
                changes.append(f"branch_prefix → {agent.branch_prefix}")
            if params.get("runtime_target_id") is not None:
                agent.runtime_target_id = str(params.get("runtime_target_id") or "").strip() or None
                changes.append(f"runtime_target_id → {agent.runtime_target_id or 'auto'}")
            if params.get("is_active") is not None:
                agent.is_active = bool(params.get("is_active"))
                changes.append(f"is_active → {agent.is_active}")

            await context.db.commit()
        return {
            "status": "updated",
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "agent_type": agent.agent_type,
                "project_id": agent.project_id,
                "thinking_level": agent.thinking_level,
                "runtime_target_id": agent.runtime_target_id,
                "branch_prefix": agent.branch_prefix,
                "is_active": agent.is_active,
            },
            "changes": changes,
        }


__all__ = [
    "AdminCreateAgentTool",
    "AdminGetAgentTool",
    "AdminListAgentsTool",
    "AdminUpdateAgentTool",
]
