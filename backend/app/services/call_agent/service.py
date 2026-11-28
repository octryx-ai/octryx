"""CallAgent — voice-optimized agent for Teams Calling."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...tools.context import ToolContext
from ...tools.registry import execute_tool_with_plugins
from ..content_security.handling import PLATFORM_RECORD_WITHOUT_WORKSPACE
from ..content_security.knowledge_fence import unfence_text
from ..content_security.model_call_scope import ModelCallScope, call_scope, model_call_scope
from ..error_facts import error_text
from ..model_gateway.dispatch_admission import DispatchAdmissionDeniedError
from ..worker_execution_profile import worker_turn_refusal
from . import heuristics
from .provider_admission import resolve_admitted_provider

# Closed-vocabulary ``error`` value for a Workspace that has not granted a model.
ADMISSION_DENIED_ERROR = "model_admission_denied"

logger = logging.getLogger(__name__)


@dataclass
class CallAgentResponse:
    """Result from CallAgent.run()."""

    # All fields have defaults to avoid TypeError
    thinking_message: str | None = None  # e.g. "Let me check that..."
    final_response: str = ""  # the actual response to speak back
    follow_up_question: str | None = None  # e.g. "What is the status of task ABC?"
    tool_calls_made: int = 0
    tools_used: list[str] = field(default_factory=list)
    error: str | None = None  # if something failed
    # Bounded ``DispatchAdmission.to_result()`` payload when the Workspace refused
    # the model (status, dispatch_owner, admission_reason, evidence, dispatched).
    admission: dict[str, Any] | None = None


# --- CallAgent Service ---

class CallAgentService:
    """Voice-optimized agent for Teams Calling."""

    def __init__(
        self,
        db: AsyncSession,
        call_agent_config: Any,
    ):
        self.db = db
        self.config = call_agent_config
        self.enabled_tools = set(getattr(call_agent_config, "enabled_tools", None) or [])
        self._tool_context: ToolContext | None = None

    @property
    def tool_context(self) -> ToolContext:
        """Lazy-create ToolContext with project config."""
        if self._tool_context is None:
            from ..run_capability.worker_profiles import worker_tool_context_state

            project_id = str(self.config.project_id)
            self._tool_context = ToolContext(
                user_id="system",
                project_ids=[project_id],
                roles=[],
                session_id=f"call-agent-{self.config.id}",
                project_config={"project_id": project_id},
                db=self.db,
                run_capability=worker_tool_context_state("call_agent"),
            )
        return self._tool_context

    async def _get_llm_provider(self, model: str | None = None) -> tuple[Any, str]:
        return await resolve_admitted_provider(
            self.db,
            project_id=self.config.project_id,
            configured_model=self.config.llm_model,
            model=model,
        )

    def _call_scope(self) -> ModelCallScope:
        return call_scope(self.config.project_id, without_workspace=PLATFORM_RECORD_WITHOUT_WORKSPACE)

    async def _llm_chat(self, messages: list[dict], model: str | None = None) -> str:
        provider, resolved_model = await self._get_llm_provider(model)

        with model_call_scope(self._call_scope()):
            result = await provider.chat(
                messages=messages,
                model=resolved_model,
                temperature=0.3,
                max_tokens=2000,
            )

        return result.get("content", "")

    async def _llm_with_tools(
        self,
        messages: list[dict],
        tool_definitions: list[dict],
        model: str | None = None,
    ) -> tuple[str, list[dict]]:
        provider, resolved_model = await self._get_llm_provider(model)

        with model_call_scope(self._call_scope()):
            result = await provider.chat(
                messages=messages,
                model=resolved_model,
                tools=tool_definitions,
                temperature=0.3,
                max_tokens=2000,
            )

        content = result.get("content", "")
        tool_calls = result.get("tool_calls", []) or []

        return content, tool_calls

    async def _execute_tool(self, tool_name: str, params: dict) -> dict:
        if tool_name not in self.enabled_tools:
            logger.warning("Tool %s not enabled for CallAgent %s", tool_name, self.config.id)
            return {"error": f"Tool not enabled: {tool_name}"}

        try:
            result = await execute_tool_with_plugins(tool_name, params, self.tool_context)
            return result
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return {"error": error_text("call_agent_tool_failed", exc)}

    def _format_tool_results(self, tool_results: list[dict]) -> str:
        return heuristics.format_tool_results(tool_results)

    def _detect_follow_up(self, response: str) -> str | None:
        return heuristics.detect_follow_up(response)

    def _extract_tool_names(self, text: str) -> list[str]:
        return heuristics.extract_tool_names(text)

    def _extract_params(self, tool_name: str, user_message: str) -> dict:
        return heuristics.extract_params(tool_name, user_message)

    async def run(
        self,
        user_message: str,
        transcript_context: str = "",
    ) -> CallAgentResponse:
        """Execute CallAgent for a user message."""
        # The worker profile's execution gate decides before any model call or tool.
        refusal = worker_turn_refusal("call_agent", prompt=user_message)
        if refusal is not None:
            return CallAgentResponse(error=refusal.status, final_response=refusal.user_message)
        try:
            return await self._answer(user_message, transcript_context)
        except DispatchAdmissionDeniedError as denied:
            return self._admission_denied(denied)
        except Exception as exc:
            logger.exception("CallAgent.run() failed")
            return CallAgentResponse(
                error=error_text("call_agent_run_failed", exc),
                final_response="Sorry, an error occurred. Please try again.",
            )

    async def _answer(self, user_message: str, transcript_context: str) -> CallAgentResponse:
        # Build context prompt
        context_parts = []
        if transcript_context:
            context_parts.append(f"Meeting Transcript:\n{transcript_context}")

        context_parts.append(f"User: {user_message}")
        context = "\n\n".join(context_parts)

        thinking_msg = self.config.thinking_message
        tool_results: list[dict] = []

        # Only run planning + tool execution if tools are configured
        if self.enabled_tools:
            tool_results = await self._run_planned_tools(context, user_message)

        # Generate final response (single LLM call when no tools)
        final_messages = self._final_messages(context, tool_results)

        # Spoken to the caller: no fence marker from a fenced tool result (fence only at a model's input).
        final_response = unfence_text(await self._llm_chat(final_messages))

        # Detect follow-up
        follow_up = self._detect_follow_up(final_response)

        return CallAgentResponse(
            thinking_message=thinking_msg if tool_results else None,
            final_response=final_response,
            follow_up_question=follow_up,
            tool_calls_made=len(tool_results),
            tools_used=[r["tool"] for r in tool_results],
        )

    async def _run_planned_tools(self, context: str, user_message: str) -> list[dict]:
        planning_messages = heuristics.planning_messages(
            self.config.system_prompt, context, self.enabled_tools
        )

        planning_response = await self._llm_chat(planning_messages)

        # Parse tool names from planning response
        tool_names = self._extract_tool_names(planning_response)

        max_calls = min(self.config.max_tool_calls or 5, len(tool_names))

        tool_results: list[dict] = []
        for tool_name in tool_names[:max_calls]:
            if tool_name not in self.enabled_tools:
                continue

            # Extract params from planning response (basic approach)
            params = self._extract_params(tool_name, user_message)
            result = await self._execute_tool(tool_name, params)

            tool_results.append({
                "tool": tool_name,
                "result": result,
            })
        return tool_results

    def _final_messages(self, context: str, tool_results: list[dict]) -> list[dict]:
        tool_context = self._format_tool_results(tool_results) if tool_results else ""
        return heuristics.final_messages(self.config.system_prompt, context, tool_context)

    def _admission_denied(self, denied: DispatchAdmissionDeniedError) -> CallAgentResponse:
        # A Workspace-policy refusal, not a failure: nothing was dispatched and
        # the bounded typed payload is preserved instead of collapsing into the
        # generic apology, which an operator cannot act on.
        logger.warning(
            "call_agent.model_admission_denied",
            # Nested, so no payload key can collide with a log-record field.
            extra={"call_agent_id": getattr(self.config, "id", None), "admission": denied.to_result()},
        )
        return CallAgentResponse(
            error=ADMISSION_DENIED_ERROR,
            final_response=(
                "This workspace has not granted a language model for call agents, "
                "so I cannot answer right now."
            ),
            admission=denied.to_result(),
        )


__all__ = ["ADMISSION_DENIED_ERROR", "CallAgentResponse", "CallAgentService"]
