"""An Agent Definition's stored revision snapshot (``agent_definition_snapshot``, checksummed and pinned by published
runs) and the execution payload built from the live row or from that snapshot (``agent_definition_payload``)."""

from typing import Any, Literal, NotRequired, TypedDict


class SnapshotDefinition(TypedDict):
    name: str
    description: str
    goal: str
    agent_type: str
    thinking_level: str
    branch_prefix: str
    system_prompt: str
    output_prompt: str
    project_id: str | None
    group_id: str | None
    runtime_target_id: str | None
    skill_preferences: dict[str, Any]
    require_self_review: bool
    is_active: bool
    # Only values that differ from the default, so the checksum never covers a default.
    tool_surface: NotRequired[str]
    reply_contract: NotRequired[Any]  # the stored value verbatim: an invalid one fails closed at runtime
    capability_ceiling: NotRequired[str]
    default_workflow_key: NotRequired[str]
    execution_mode: NotRequired[str]
    runtime_preference: NotRequired[str]
    chat_selectable: NotRequired[Literal[True]]
    tools_deny: NotRequired[list[str]]


class SnapshotStep(TypedDict):
    position: int
    name: str
    step_type: str
    instructions: str
    success_criteria: str
    allowed_tools: list[str]
    step_config: dict[str, Any]
    is_enabled: bool


class DefinitionSnapshot(TypedDict):
    definition: SnapshotDefinition
    steps: list[SnapshotStep]


class AgentStepPayload(TypedDict):
    id: str  # empty for a snapshot position with no live step
    position: int
    name: str
    stepType: str
    instructions: str
    successCriteria: str
    allowedTools: list[str]
    stepConfig: dict[str, Any]
    isEnabled: bool


class AgentPayload(TypedDict):
    id: str
    name: str
    description: str
    goal: str
    agentType: str
    thinkingLevel: str
    branchPrefix: str
    requireSelfReview: bool
    toolSurface: Any  # verbatim, so an invalid value reaches the execution gate
    replyContract: Any  # verbatim, so an invalid value fails closed at runtime
    systemPrompt: str
    outputPrompt: str
    projectId: str
    groupId: str
    groupName: str
    runtimeTargetId: str
    skillPreferences: dict[str, Any]
    isActive: bool
    steps: list[AgentStepPayload]
    builtinKey: str
    capabilityCeiling: str
    defaultWorkflowKey: str
    runtimePreference: str
    chatSelectable: bool
    toolsDeny: list[str]
    executionMode: NotRequired[Literal["coding_delivery"]]


__all__ = [
    "AgentPayload",
    "AgentStepPayload",
    "DefinitionSnapshot",
    "SnapshotDefinition",
    "SnapshotStep",
]
