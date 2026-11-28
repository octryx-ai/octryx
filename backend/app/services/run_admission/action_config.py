"""An Action runs either a workflow run or an agent with a prompt."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .denials import ACTION_AGENT_AND_WORKFLOW, denial, denial_http

WORKFLOW_RUN_KEY = "workflow_run"


def names_agent_and_workflow(config: Any) -> bool:
    data = config if isinstance(config, dict) else {}
    return bool(str(data.get("agent_definition_id") or "").strip()) and bool(data.get(WORKFLOW_RUN_KEY))


async def action_config_refusal(db: AsyncSession, config: Any) -> dict[str, object] | None:
    data = config if isinstance(config, dict) else {}
    if names_agent_and_workflow(data):
        return denial(ACTION_AGENT_AND_WORKFLOW)
    return None


async def require_action_config(db: AsyncSession, config: Any) -> None:
    refused = await action_config_refusal(db, config)
    if refused is not None:
        raise denial_http(str(refused["code"]), status_code=422)
