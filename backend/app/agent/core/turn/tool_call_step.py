"""Resolve which plan step a tool call belongs to and which tools that step allows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ..guards.response_guards import get_step_allowed_tools, get_step_field


@dataclass(kw_only=True)
class ToolCallStep:
    current_step_index: int
    current_step_tool_activity: bool
    current_allowed_tool_names: set[str]
    configured_step_allowed_tool_names: set[str]


def _step_allowed_tool_names(active_steps: list[dict[str, Any]], step_index: int) -> set[str]:
    names: set[str] = set()
    if 0 <= step_index < len(active_steps):
        names.update(
            str(tool_name or "").strip()
            for tool_name in get_step_allowed_tools(active_steps[step_index])
            if str(tool_name or "").strip()
        )
    return names


async def resolve_tool_call_step(
    db: AsyncSession,
    *,
    tool_context: ToolContext,
    tool_name: str,
    active_steps: list[dict[str, Any]],
    current_step_index: int,
    current_step_tool_activity: bool,
    current_allowed_tool_names: set[str],
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]],
) -> ToolCallStep:
    """Advance the step when the call belongs to a later one, unless the delivery gate holds the current step."""
    explicit_step_allowed_tool_names = _step_allowed_tool_names(active_steps, current_step_index)
    step_contract_allowed_tool_names = {*current_allowed_tool_names, *explicit_step_allowed_tool_names}
    next_step_index, next_step_tool_activity, effective_allowed_tool_names = resolve_allowed_tools_for_step_tool_call(
        active_steps=active_steps,
        current_step_index=current_step_index,
        current_step_tool_activity=current_step_tool_activity,
        current_allowed_tool_names=step_contract_allowed_tool_names,
        tool_name=tool_name,
    )
    if next_step_index != current_step_index and 0 <= next_step_index < len(active_steps):
        from ....services.coding_delivery_gate import delivery_step_advance_blocked

        source_step = active_steps[current_step_index] if 0 <= current_step_index < len(active_steps) else {}
        advance_blocked = await delivery_step_advance_blocked(
            db,
            session_id=tool_context.session_id,
            source_step_type=str(get_step_field(source_step, "stepType", "step_type", "") or ""),
            target_allowed_tools={
                str(name or "").strip()
                for name in get_step_allowed_tools(active_steps[next_step_index])
                if str(name or "").strip()
            },
        )
        if advance_blocked:
            next_step_index = current_step_index
            next_step_tool_activity = current_step_tool_activity
            effective_allowed_tool_names = step_contract_allowed_tool_names
    return ToolCallStep(
        current_step_index=next_step_index,
        current_step_tool_activity=next_step_tool_activity,
        current_allowed_tool_names=effective_allowed_tool_names,
        configured_step_allowed_tool_names=_step_allowed_tool_names(active_steps, next_step_index),
    )
