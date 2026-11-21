"""Agent Engine – Core execution loop with multi-provider support."""

import inspect
import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import ControlPlaneRuntimeTarget, LLMModel
from ...services.budget import enforce_budget_limits
from ...services.content_security.model_call_scope import model_call_scope, session_call
from ...services.control_plane_service import resolve_control_plane_runtimes
from ...services.llm_cache import (
    lookup_cached_llm_response,
    select_llm_cache_ttl_seconds,
    store_llm_cache_response,
)
from ...services.llm_cache.dispatch_policy import response_cache_allowed
from ...services.repository_arg_inference import WORKSPACE_ROOT as _ENGINE_WORKSPACE_ROOT
from ...services.repository_arg_inference import _infer_repo_tool_args
from ...services.session.workspace import get_session_workspace_root
from ...services.sync_report_formatting import (
    _format_recent_bitbucket_commits_report,
    _format_repository_knowledge_sync_report,
    _format_repository_noop_sync_report,
)
from ...tools.registry import execute_tool_with_plugins
from ..core.assistant_message import persist_traced_assistant_message as _persist_traced_assistant_message
from ..core.context.engine_limits import APPROX_CHARS_PER_TOKEN
from ..core.context.engine_limits import map_reasoning_effort as _map_reasoning_effort
from ..core.context.engine_limits import max_completion_tokens_for_run as _max_completion_tokens_for_run
from ..core.context.run_context import prepare_agent_run as _prepare_agent_run
from ..core.execution_support import record_engine_turn_usage_event as _record_usage_event
from ..core.guards.response_guards import allows_noop_step_completion as _allows_noop_step_completion
from ..core.guards.response_guards import (
    assistant_no_tool_response_signature as _assistant_no_tool_response_signature,
)
from ..core.guards.response_guards import (
    assistant_no_tool_response_similarity as _assistant_no_tool_response_similarity,
)
from ..core.guards.response_guards import build_required_tool_reminder as _build_required_tool_reminder
from ..core.guards.response_guards import build_stalled_step_message as _build_stalled_step_message
from ..core.guards.response_guards import (
    is_non_substantive_assistant_response as _is_non_substantive_assistant_response,
)
from ..core.guards.response_guards import is_transitional_assistant_response as _is_transitional_assistant_response
from ..core.guards.response_guards import is_transitional_tool_call_preamble as _is_transitional_tool_call_preamble
from ..core.guards.response_guards import looks_like_step_completion_summary as _looks_like_step_completion_summary
from ..core.guards.response_guards import (
    resolve_allowed_tools_for_step_tool_call as _resolve_allowed_tools_for_step_tool_call,
)
from ..core.guards.step_progress import max_iterations_for_agent_step as _max_iterations_for_agent_step
from ..core.guards.summary_domains import summary_domains_satisfied_by_result as _summary_domains_satisfied_by_result
from ..core.runtime.standard_loop import run_standard_agent_loop as _run_standard_agent_loop
from ..core.runtime.standard_loop_inputs import StandardLoopInputs
from ..core.runtime.turn_execution_binding import scoped_turn_execution_binding
from ..harness.activation import select_turn_loop
from ..providers import get_provider
from ._engine_events import AgentEvent
from ._engine_run_preparation import bootstrap_workspace_repository_if_configured
from ._engine_run_scope import run_scope
from ._engine_turn_admission import admit_turn
from .messages._engine_message_helpers import (
    _build_current_step_prompt,
    _exclude_tool_definitions,
    _filter_tool_definitions,
    _has_pending_approval_result,
    _trim_messages_to_budget,
)
from .messages._engine_tool_compaction import _compact_tool_result_for_model
from .pre_dispatch._pre_dispatch_runtime_guard import prepare_pre_dispatch_runtime_messages
from .pre_dispatch._research_evidence_binding import research_evidence_context
from .pre_dispatch._research_evidence_context import research_attempt_guard
from .runtime._engine_runtime_fallback import _chat_with_runtime_fallback as _chat_with_runtime_fallback_impl
from .runtime._engine_runtime_fallback import _normalize_runtime_chat_result
from .runtime._engine_runtime_retry_policy import RuntimeRetryPolicy

settings = get_settings()
logger = logging.getLogger(__name__)
WORKSPACE_ROOT = _ENGINE_WORKSPACE_ROOT


async def _resolve_model_context_cap(
    db: AsyncSession,
    *,
    runtime_target_id: str | None,
) -> int | None:
    target: ControlPlaneRuntimeTarget | None = None
    if runtime_target_id:
        target = await db.get(ControlPlaneRuntimeTarget, runtime_target_id)
    if not target:
        runtimes = await resolve_control_plane_runtimes(db, runtime_target_id=runtime_target_id)
        selected_runtime = runtimes[0] if runtimes else None
        if selected_runtime and selected_runtime.get("target_id"):
            target = await db.get(ControlPlaneRuntimeTarget, str(selected_runtime["target_id"]))
    if not target:
        return None

    model = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == target.provider_id,
                LLMModel.model_id == target.model_id,
            )
        )
    ).scalar_one_or_none()
    if not model:
        return None
    if model.planner_context_budget:
        return int(model.planner_context_budget)
    if model.context_length:
        return max(1000, int(model.context_length * 0.7))
    return None


async def _chat_with_runtime_fallback(
    runtimes: list[dict],
    *,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int = 4096,
    reasoning_effort: str | None = None,
    request_timeout_seconds: float = 150.0,
    retry_policy: RuntimeRetryPolicy | None = None,
    context_guard: Any | None = None,
) -> tuple[dict, dict, list[dict[str, Any]]]:
    return await _chat_with_runtime_fallback_impl(
        runtimes,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        request_timeout_seconds=request_timeout_seconds,
        get_provider_func=get_provider,
        retry_policy=retry_policy,
        **({"context_guard": context_guard} if context_guard is not None else {}),
    )


@scoped_turn_execution_binding
async def run_agent(
    session_id: str,
    user_message: str,
    user_id: str,
    project_id: str | None,
    agent_type: str,
    db: AsyncSession,
    runtime_target_id: str | None = None,
    thinking_level: str | None = None,
    agent_definition: dict | None = None,
    parent_session_id: str | None = None,
    sub_agent_depth: int = 0,
    max_iterations: int | None = None,
    run_origin: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the primary agent loop for one user turn.

    ``run_origin`` binds the turn to a Product Run; only the Chat entry points pass it.
    """
    logger.info(
        "agent.run.start",
        extra={
            "session_id": session_id,
            "project_id": project_id,
            "agent_type": agent_type,
            "runtime_target_id": runtime_target_id,
        },
    )
    async with run_scope(db, session_id=session_id, origin=run_origin, user_id=user_id) as product_run:
        workspace_root = await get_session_workspace_root(db, session_id)
        prepared = await _prepare_agent_run(
            db=db,
            session_id=session_id,
            user_message=user_message,
            user_id=user_id,
            project_id=project_id,
            agent_type=agent_type,
            runtime_target_id=runtime_target_id,
            thinking_level=thinking_level,
            agent_definition=agent_definition,
            parent_session_id=parent_session_id,
            sub_agent_depth=sub_agent_depth,
            workspace_root=str(workspace_root),
            resolve_model_context_cap=_resolve_model_context_cap,
            resolve_control_plane_runtimes_func=resolve_control_plane_runtimes,
            filter_tool_definitions=_filter_tool_definitions,
            exclude_tool_definitions=_exclude_tool_definitions,
            trim_messages_to_budget=_trim_messages_to_budget,
        )
        logger.info(
            "agent.run.prepared",
            extra={
                "session_id": session_id,
                "history_count": prepared.history_count,
                "tool_definition_count": len(prepared.tool_definitions),
                "runtime_count": len(prepared.runtimes),
            },
        )
        admission = await admit_turn(
            db=db,
            session_id=session_id,
            prepared=prepared,
            agent_definition=agent_definition,
            runtime_target_id=runtime_target_id,
            product_run_stamp=product_run.stamp,
            resolve_runtimes_func=resolve_control_plane_runtimes,
            persist_traced_assistant_message_func=_persist_traced_assistant_message,
        )
        await product_run.record_admission(admission)
        if not admission.admitted:
            yield AgentEvent(role="assistant", content=admission.blocked_message)
            return
        from app.agent.engine._turn_tools_persistence import (
            persist_synthesized_tool_assistant as _persist_synthesized_tool_assistant,
        )

        from ..core.turn.turn_tools import execute_tool_call_for_turn as _execute_tool_call_for_turn

        tool_context = prepared.tool_context
        runtime_settings = prepared.runtime_settings
        await bootstrap_workspace_repository_if_configured(
            workspace_root=workspace_root,
            project_config=tool_context.project_config,
            session_id=session_id,
        )
        async def _chat_with_budget_guard(
            *,
            runtimes: list[dict],
            messages: list[dict],
            tools: list[dict] | None,
            max_tokens: int = 4096,
            reasoning_effort: str | None = None,
            request_timeout_seconds: float = 150.0,
            retry_policy: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> tuple[dict, dict, list[dict[str, Any]]]:
            def _annotate_runtime_attempts_with_pre_dispatch(
                runtime_attempts: list[dict[str, Any]],
                token_pressure_payload: dict[str, Any],
            ) -> list[dict[str, Any]]:
                if not runtime_attempts:
                    return runtime_attempts
                annotated_attempts = [dict(item) for item in runtime_attempts]
                annotated_attempts[-1]["token_pressure"] = dict(token_pressure_payload)
                return annotated_attempts

            # Content policies run at the provider boundary for every driver (content_security.model_call).
            research_context = await research_evidence_context(
                db=db, tool_context=tool_context, session_metadata=prepared.session_metadata,
                messages=messages, runtimes=runtimes, tools=tools, max_tokens=max_tokens)
            pre_dispatch_guard = prepare_pre_dispatch_runtime_messages(
                research_context=research_context,
                messages=messages,
                runtimes=runtimes,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                approx_chars_per_token=int(runtime_settings.get("approx_chars_per_token") or APPROX_CHARS_PER_TOKEN),
            )
            dispatch_messages = pre_dispatch_guard.messages
            context_guard = research_attempt_guard(research_context, dispatch_messages) if research_context else None
            cache_enabled_for_dispatch = response_cache_allowed(
                run_origin=run_origin, tools=tools, messages=dispatch_messages
            )
            cached_result = (
                await lookup_cached_llm_response(
                    db,
                    runtimes=runtimes,
                    messages=dispatch_messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
                if cache_enabled_for_dispatch
                else None
            )
            if cached_result is not None:
                response, runtime, runtime_attempts = _normalize_runtime_chat_result(cached_result)
                if context_guard is not None:
                    context_guard(runtime, dispatch_messages)
                return (
                    response,
                    runtime,
                    _annotate_runtime_attempts_with_pre_dispatch(
                        runtime_attempts,
                        pre_dispatch_guard.token_pressure_payload,
                    ),
                )
            await enforce_budget_limits(
                db,
                session_id=session_id,
                user_id=user_id,
                project_id=project_id,
                runtimes=runtimes,
                messages=dispatch_messages,
                max_completion_tokens=max_tokens,
                approx_chars_per_token=int(runtime_settings.get("approx_chars_per_token") or APPROX_CHARS_PER_TOKEN),
            )
            fallback_kwargs: dict[str, Any] = {
                "runtimes": runtimes,
                "messages": dispatch_messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
            }
            if "request_timeout_seconds" in inspect.signature(_chat_with_runtime_fallback).parameters:
                fallback_kwargs["request_timeout_seconds"] = request_timeout_seconds
            if "retry_policy" in inspect.signature(_chat_with_runtime_fallback).parameters:
                fallback_kwargs["retry_policy"] = retry_policy
            fallback_kwargs.update(kwargs)
            if context_guard is not None:
                fallback_kwargs["context_guard"] = context_guard
            with model_call_scope(session_call(project_id, session_id=session_id, user_id=user_id)):
                raw_result = await _chat_with_runtime_fallback(**fallback_kwargs)
            if not isinstance(raw_result, tuple):
                raw_result = tuple(raw_result)
            response, runtime, attempts = _normalize_runtime_chat_result(raw_result)
            attempts = _annotate_runtime_attempts_with_pre_dispatch(
                attempts,
                pre_dispatch_guard.token_pressure_payload,
            )
            if cache_enabled_for_dispatch:
                ttl_seconds, cache_scope = select_llm_cache_ttl_seconds(
                    tools=tools,
                    default_ttl_seconds=int(runtime_settings.get("llm_cache_ttl_seconds") or 0),
                    tools_ttl_seconds=int(runtime_settings.get("llm_cache_tools_ttl_seconds") or 0),
                )
                await store_llm_cache_response(
                    db,
                    provider_id=str(runtime.get("provider_id") or runtime.get("provider_name") or "").strip(),
                    model_id=str(runtime.get("model") or "").strip(),
                    messages=dispatch_messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                    response=response,
                    ttl_seconds=ttl_seconds,
                    cache_scope=cache_scope,
                )
            return response, runtime, attempts

        # Issue #91: if this session is running a flow definition, delegate to flow orchestration
        if prepared.current_session and prepared.current_session.flow_definition_version_id:
            from ...services.flow_orchestration.runner import execute_flow_version

            orchestrator_run = await execute_flow_version(
                db=db,
                flow_version_id=prepared.current_session.flow_definition_version_id,
                parent_session_id=session_id,
                project_id=project_id,
                triggered_by_node_id=prepared.current_session.flow_node_id,
                user_id=user_id,
                agent_type=agent_definition.get("agent_type") if agent_definition else "change",
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                agent_definition=agent_definition,
            )
            await db.commit()
            # The completion as a supported event; only closed facts (run id, status column) are
            # stated, the merged output stays on the orchestrator run record.
            yield AgentEvent(
                role="assistant",
                content=f"Workflow run {orchestrator_run.id} ended with status {orchestrator_run.status}.",
            )
            return

        async for event in select_turn_loop(_run_standard_agent_loop, prepared=prepared, agent_definition=agent_definition)(
            StandardLoopInputs(
                prepared=prepared,
                session_id=session_id,
                user_id=user_id,
                db=db,
                runtime_target_id=runtime_target_id,
                thinking_level=thinking_level,
                agent_definition=agent_definition,
                max_iterations=max_iterations,
                map_reasoning_effort=_map_reasoning_effort,
                max_completion_tokens_for_run=_max_completion_tokens_for_run,
                max_iterations_for_agent_step=_max_iterations_for_agent_step,
                filter_tool_definitions=_filter_tool_definitions,
                build_current_step_prompt=_build_current_step_prompt,
                normalize_runtime_chat_result=_normalize_runtime_chat_result,
                chat_with_runtime_fallback=_chat_with_budget_guard,
                is_transitional_assistant_response=_is_transitional_assistant_response,
                is_transitional_tool_call_preamble=_is_transitional_tool_call_preamble,
                is_non_substantive_assistant_response=_is_non_substantive_assistant_response,
                allows_noop_step_completion=_allows_noop_step_completion,
                build_required_tool_reminder=_build_required_tool_reminder,
                build_stalled_step_message=_build_stalled_step_message,
                assistant_no_tool_response_signature=_assistant_no_tool_response_signature,
                assistant_no_tool_response_similarity=_assistant_no_tool_response_similarity,
                looks_like_step_completion_summary=_looks_like_step_completion_summary,
                execute_tool_call_for_turn=_execute_tool_call_for_turn,
                infer_repo_tool_args=_infer_repo_tool_args,
                resolve_allowed_tools_for_step_tool_call=_resolve_allowed_tools_for_step_tool_call,
                compact_tool_result_for_model=_compact_tool_result_for_model,
                summary_domains_satisfied_by_result=_summary_domains_satisfied_by_result,
                execute_tool=execute_tool_with_plugins,
                record_usage_event=_record_usage_event,
                persist_traced_assistant_message=_persist_traced_assistant_message,
                persist_synthesized_tool_assistant=_persist_synthesized_tool_assistant,
                format_repository_noop_sync_report=_format_repository_noop_sync_report,
                format_repository_knowledge_sync_report=_format_repository_knowledge_sync_report,
                format_recent_bitbucket_commits_report=_format_recent_bitbucket_commits_report,
                has_pending_approval_result=_has_pending_approval_result,
                event_factory=AgentEvent,
            )
        ):
            yield event
