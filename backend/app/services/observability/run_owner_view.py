"""What the owner of a chat sees in its run details.

Owners see their messages, tool calls and results. The platform's own instructions (system, personality, memory and
skills prompts, the prompt configuration, the platform's system context and the workflow step's instructions) are
visible to global admins only; for anyone else they are replaced by a fixed note. The step's name and type stay
visible. Applied to the serialized trace, after the owner check.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

PLATFORM_PROMPT_KEYS = ("system_prompt", "personality_prompt", "memory_prompt", "skills_prompt", "prompt_config",
                        "system_context")
# Platform-written fields inside the current workflow step.
PLATFORM_STEP_KEYS = ("instructions",)
HIDDEN_NOTE = "[platform instructions — visible to admins only]"


def run_details_for_viewer(payload: dict[str, Any] | None, *, is_admin: bool) -> dict[str, Any] | None:
    if payload is None or is_admin:
        return payload
    context = dict(payload.get("contextSnapshot") or {})
    for key in PLATFORM_PROMPT_KEYS:
        if key in context:
            context[key] = HIDDEN_NOTE if isinstance(context[key], str) else {}
    step = context.get("current_step")
    if isinstance(step, dict):
        context["current_step"] = {key: HIDDEN_NOTE if key in PLATFORM_STEP_KEYS else value
                                   for key, value in step.items()}
    messages = [
        {"role": "system", "content": HIDDEN_NOTE}
        if isinstance(message, dict) and message.get("role") == "system" else message
        for message in payload.get("inputMessages") or []
    ]
    return {**payload, "contextSnapshot": context, "inputMessages": messages}


async def run_details_for_user(db: AsyncSession, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """``run_details_for_viewer`` for the signed-in user (global admins see the platform prompts)."""
    from ..admin.governance.admin_access_service import is_global_admin

    return run_details_for_viewer(payload, is_admin=await is_global_admin(db, user_id))


__all__ = ["HIDDEN_NOTE", "run_details_for_user", "run_details_for_viewer"]
