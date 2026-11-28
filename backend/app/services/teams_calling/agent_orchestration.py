# ruff: noqa: E501
"""Agent invocation for Teams calls."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_catalog.out_of_turn import prompt_set_for

from ...models import ChannelConfig
from ...services.call_agent import get_call_agent_config
from .call_session_state import get_call_state

logger = logging.getLogger(__name__)


async def agent_response(
    text: str,
    call_id: str,
    channel_id: str,
    db: AsyncSession,
    project_id: str | None = None,
) -> str:
    import sys as _sys
    from types import SimpleNamespace

    from ...services.call_agent import CallAgentService

    if not project_id or not channel_id:
        print(
            f"[CALL DEBUG] _agent_response: MISSING project_id={repr(project_id)} channel_id={repr(channel_id)}",
            file=_sys.stderr,
            flush=True,
        )
        logger.warning("_agent_response: missing project_id or channel_id for call %s", call_id)
        return ""

    try:
        # Load channel config directly — no separate CallAgentConfig table needed
        try:
            channel_pk = int(channel_id)
        except ValueError:
            print(f"[CALL DEBUG] _agent_response: invalid channel_id={repr(channel_id)}", file=_sys.stderr, flush=True)
            logger.warning("_agent_response: invalid channel_id %r for call %s", channel_id, call_id)
            return ""

        result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == channel_pk))
        channel = result.scalar_one_or_none()
        if channel is None:
            config = await get_call_agent_config(db, project_id=project_id)
            if config is None:
                return "Sorry, no active call agent is configured for this project."
            call_state = get_call_state(call_id)
            service = CallAgentService(db, config)
            agent_result = await service.run(text, transcript_context=call_state.transcript_text)
            if agent_result.error:
                logger.error("_agent_response error for call %s: call_agent_failed", call_id)
                return ""
            return agent_result.final_response

        raw = channel.config or {}
        chan_cfg = json.loads(raw) if isinstance(raw, str) else (raw or {})

        # Parse enabled_tools from comma-separated string
        tools_raw = str(chan_cfg.get("call_agent_enabled_tools") or "").strip()
        enabled_tools = [t.strip() for t in tools_raw.split(",") if t.strip()] if tools_raw else []

        call_prompts = await prompt_set_for(db, workspace_id=project_id)
        _default_prompt = call_prompts.render("knowledge.teams.call_default_system")
        config = SimpleNamespace(
            project_id=project_id,
            channel_id=channel_id,
            llm_model=str(chan_cfg.get("call_agent_llm_model") or "").strip() or None,
            system_prompt=str(chan_cfg.get("call_agent_system_prompt") or _default_prompt),
            thinking_message=str(chan_cfg.get("call_agent_thinking_message") or "One moment please."),
            max_tool_calls=int(chan_cfg.get("call_agent_max_tool_calls") or 5),
            enabled_tools=enabled_tools,
            is_active=True,
        )

        print(
            f"[CALL DEBUG] _agent_response: calling CallAgentService.run() model={config.llm_model} tools={enabled_tools}",
            file=_sys.stderr,
            flush=True,
        )
        call_state = get_call_state(call_id)
        transcript_context = call_state.transcript_text

        service = CallAgentService(db, config)
        agent_result = await service.run(text, transcript_context=transcript_context)

        if agent_result.error:
            # The agent error is free provider text: only a closed code is logged.
            print("[CALL DEBUG] _agent_response: agent ERROR: call_agent_failed", file=_sys.stderr, flush=True)
            logger.error("_agent_response error for call %s: call_agent_failed", call_id)
            return ""

        print(
            f"[CALL DEBUG] _agent_response: SUCCESS response chars={len(agent_result.final_response or '')}",
            file=_sys.stderr,
            flush=True,
        )
        return agent_result.final_response

    except Exception as _exc:
        print(f"[CALL DEBUG] _agent_response: EXCEPTION: error_type={type(_exc).__name__}", file=_sys.stderr, flush=True)
        logger.exception("_agent_response failed for call %s", call_id)
        return ""


async def generate_meeting_summary(
    transcript: str, channel_id: str | None, project_id: str | None, db: AsyncSession
) -> str:
    from types import SimpleNamespace

    from ...services.call_agent import CallAgentService

    # Load channel config for LLM model
    llm_model = None
    if channel_id:
        try:
            channel_pk = int(channel_id)
            result = await db.execute(select(ChannelConfig).where(ChannelConfig.id == channel_pk))
            channel = result.scalar_one_or_none()
            if channel:
                raw = channel.config or "{}"
                config = json.loads(raw) if isinstance(raw, str) else (raw or {})
                llm_model = str(config.get("call_agent_llm_model") or "").strip() or None
        except Exception:
            pass

    summary_prompts = await prompt_set_for(db, workspace_id=project_id)
    summary_config = SimpleNamespace(
        project_id=project_id or "",
        channel_id=channel_id or "",
        llm_model=llm_model,
        system_prompt=summary_prompts.render("knowledge.teams.meeting_summary_system"),
        thinking_message="",
        max_tool_calls=0,
        enabled_tools=[],
        is_active=True,
    )

    service = CallAgentService(db, summary_config)
    result = await service.run(
        user_message=summary_prompts.render("knowledge.teams.meeting_summary_request"),
        transcript_context=transcript,
    )

    if result.error:
        logger.error("Meeting summary LLM error: %s", result.error)
        return ""

    return result.final_response or ""
