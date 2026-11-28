"""Shared tool context types without registry side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    user_id: str
    project_ids: list[str]
    roles: list[str]
    session_id: str
    project_config: dict
    current_user_message: str | None = None
    db: Any | None = None
    workspace_root: str | None = None
    system_context: dict[str, Any] | None = None
    parent_session_id: str | None = None
    sub_agent_depth: int = 0
    agent_definition: dict[str, Any] | None = None
    capability_type: str | None = None
    agent_mode_key: str | None = None
    run_capability: dict[str, Any] | None = None
    request_id: str | None = None
    prompt_config: dict[str, Any] | None = None
    turn_context_snapshot: dict[str, Any] | None = None
    # Frozen at run preparation: traces read it, not the session row a later turn may have rewritten.
    execution_profile_trace: dict[str, Any] | None = None
    turn_tool_history: list[dict[str, Any]] | None = None
    tooling_metadata: dict[str, Any] | None = None
    discovered_tool_names: set[str] = field(default_factory=set)
    deferred_tool_catalog: dict[str, dict[str, Any]] | None = None
    chat_direct_tool_names: set[str] = field(default_factory=set)
    # A repeated tool_search query gets a short answer so a weak model's retry loop ends.
    tool_search_queries: dict[str, list[str]] = field(default_factory=dict)
    # Server-owned, never model-supplied; a re-checking tool consumes its mark once, so one request costs one approval.
    enforced_approval_fingerprints: set[str] = field(default_factory=set)
    # Server-owned like the marks above: after an admitted write runs, what it created joins the plan's scope.
    chat_write_plan_calls: set[str] = field(default_factory=set)
    chat_write_plan_filled: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_refs: dict[str, dict[str, str]] = field(default_factory=dict)
    connection_id: str | None = None
    # It may only raise the Workspace's level; effect rules read it synchronously at tool dispatch.
    session_data_policy: dict[str, Any] | None = None
    # Never from model/request input: allows a published workflow's own high-risk actions; project deny rules apply.
    workflow_platform_action: bool = False
    turn_model: str | None = None
    # ``None`` means nothing narrows (switch off, platform admin, no chat).
    work_role_grant: Any | None = None
    mcp_caller: Any | None = None
