"""The inputs of ``prepare_agent_run`` and the state its preparation stages fill in order."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ....models import Message, Session
from ..types import ChatMessage, RuntimeSettings, RuntimeTarget, ToolDefinition


@dataclass(kw_only=True)
class AgentRunRequest:
    """The arguments of one ``prepare_agent_run`` call; unknown or missing names raise ``TypeError``."""

    db: AsyncSession
    session_id: str
    user_message: str
    user_id: str
    project_id: str | None
    agent_type: str
    runtime_target_id: str | None
    thinking_level: str | None
    agent_definition: dict | None
    parent_session_id: str | None
    sub_agent_depth: int
    workspace_root: str
    resolve_model_context_cap: Any
    resolve_control_plane_runtimes_func: Any
    filter_tool_definitions: Any
    exclude_tool_definitions: Any
    trim_messages_to_budget: Any


@dataclass(kw_only=True)
class RunPreparation:
    """What the preparation stages have resolved so far; each stage reads earlier fields and sets its own."""

    # Session and routing.
    current_session: Session | None
    session_metadata: dict[str, Any]
    routing_resolution: Any
    agent_type: str
    execution_profile_metadata: dict[str, Any]
    agent_mode: Any = None
    capability_type: str = ""
    # History and identity.
    personality: Any = None
    all_history: list[Message] = field(default_factory=list)
    session_summary: Any = None
    session_summary_references: Any = None
    current_turn_message: Message | None = None
    existing_thread_context: dict[str, Any] = field(default_factory=dict)
    user_roles: list[str] = field(default_factory=list)
    tool_domain_config: dict[str, Any] = field(default_factory=dict)
    # Context plan and prompt fragments.
    context_plan: Any = None
    scenario_budget_override: bool = False
    model_context_cap: Any = None
    personality_prompt: str = ""
    skills_prompt: str = ""
    engineering_knowledge_prompt: str = ""
    engineering_runtime_metadata: dict[str, Any] = field(default_factory=dict)
    context_compaction_prompt: str = ""
    session_entities: list[dict[str, Any]] = field(default_factory=list)
    entity_context_prompt: str = ""
    checkpoint_context_prompt: str = ""
    # Project configuration and tool surface.
    project_config: dict[str, Any] = field(default_factory=dict)
    user_project_ids: list[str] = field(default_factory=list)
    tool_workspace_root: Any = None
    tool_routing_resolution: Any = None
    system_prompt_variant_routing: Any = None
    prompt_config_metadata: dict[str, Any] = field(default_factory=dict)
    repo_microagents_prompt: str = ""
    repo_knowledge_prompt: str = ""
    evidence_grounding_prompt: str = ""
    memory_prompt: str = ""
    # Messages, runtimes and tools.
    summary_context_msgs: list[ChatMessage] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)
    system_context: dict[str, Any] | None = None
    chat_choice_settled: bool = False
    system_prompt: str = ""
    current_turn_content: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    runtimes: list[RuntimeTarget] = field(default_factory=list)
    runtime_settings: RuntimeSettings = field(default_factory=dict)
    tool_context: ToolContext | None = None
    tool_definitions: list[ToolDefinition] = field(default_factory=list)

    @property
    def strategy_decision(self) -> Any:
        return self.routing_resolution.strategy_decision

    @property
    def chat_connector_writes(self) -> Any:
        return self.routing_resolution.run_capability.chat_connector_writes
