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
    # Frozen at run preparation (services/run_capability): the run's capability
    # class, whether it is enforced, its source and the session's escalation
    # decision. ``None`` for contexts built outside a prepared run.
    run_capability: dict[str, Any] | None = None
    request_id: str | None = None
    prompt_config: dict[str, Any] | None = None
    turn_context_snapshot: dict[str, Any] | None = None
    # Frozen at run preparation: the bounded, redacted trace projection of this
    # run's execution profile. Traces record it instead of re-reading the session
    # row, which a later turn of the same session may already have rewritten.
    execution_profile_trace: dict[str, Any] | None = None
    # Evidence collected earlier in this turn. Tools that compose from evidence
    # (create_presentation) read it instead of inventing their inputs.
    turn_tool_history: list[dict[str, Any]] | None = None
    tooling_metadata: dict[str, Any] | None = None
    # Lazy tool discovery (approach A): long-tail tools the model activated this
    # run via tool_schema_get; the per-iteration tool surface includes these so a
    # discovered tool becomes natively callable on the next step.
    discovered_tool_names: set[str] = field(default_factory=set)
    # A chat turn's deferred tools (``services/chat_deferred_tools``): offered, but sent to the model by name only until
    # ``tool_search`` loads their schemas (then ``discovered_tool_names`` holds them). ``None`` outside a chat turn.
    deferred_tool_catalog: dict[str, dict[str, Any]] | None = None
    # The offered tools a chat turn sends in full besides its core (``chat_deferred_tools.direct_tool_names``).
    chat_direct_tool_names: set[str] = field(default_factory=set)
    # The tool_search queries this turn already answered (normalised query -> loaded names): a repeat gets a short
    # answer so a weak model's retry loop ends.
    tool_search_queries: dict[str, list[str]] = field(default_factory=dict)
    # Approval fingerprints registry dispatch already enforced for this context.
    # A tool that re-checks governance immediately before reaching a remote
    # service consumes its own mark exactly once, so one governed request costs
    # one approval grant and one audit row instead of two. Server-owned: nothing
    # model-supplied ever reaches this set.
    enforced_approval_fingerprints: set[str] = field(default_factory=set)
    # Chat writes the confirmed write plan admitted (``run_capability/chat_write_plan``): after one runs, what it
    # created (an issue key, a branch) joins the plan's scope. Server-owned like the marks above.
    chat_write_plan_calls: set[str] = field(default_factory=set)
    # The confirmed fields the plan filled into an admitted call that left them out (mark -> fields), for its result.
    chat_write_plan_filled: dict[str, dict[str, Any]] = field(default_factory=dict)
    # What admitted a call the central gate let through (``{"approval_id"}`` or ``{"write_plan_id"}``), keyed like the
    # marks above; a tool that audits its writes (custom REST, ``rest_connector/runs``) names it in its audit row.
    approval_refs: dict[str, dict[str, str]] = field(default_factory=dict)
    # The connection a routed connector call runs on: a named connection's id or ``default``.
    # Set only by ``named_connections.tool_routing``; ``None`` outside a routed call.
    connection_id: str | None = None
    # The session's ``data_policy`` block (it may only raise the Workspace's level); read by the effect rules that
    # are checked synchronously at tool dispatch, e.g. "MCP server access: off" (settings review, finding 5).
    session_data_policy: dict[str, Any] | None = None
    # Set only by ``workflow_runs.platform.dispatch.tool_context``: the call is a platform action step of a published
    # workflow run. The published workflow is the explicit allow for its own high-risk actions (e.g. ``jira.comment``
    # in Jira intake); project deny rules still apply. Never set from model or request input.
    workflow_platform_action: bool = False
    # The model this turn runs on (first resolved runtime). Used to mark AI-written output (services/ai_marking);
    # ``None`` outside an agent turn, and then nothing is marked.
    turn_model: str | None = None
    # A chat turn's work-role grant (``services/work_role_model.surfaces``): set only when the Workspace's
    # role-based tools narrow this person; ``None`` means nothing narrows (switch off, platform admin, no chat).
    work_role_grant: Any | None = None
