"""Shared helpers for the test_chat_connector_writes_* modules."""

from __future__ import annotations

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.context.run_context_tooling import build_run_context_tool_definitions
from app.agent.core.context.turn_tool_surface import resolve_turn_tool_surface
from app.agent.engine.messages._engine_message_helpers import _exclude_tool_definitions, _filter_tool_definitions
from app.tools.context import ToolContext
from app.tools.registry import get_all_tools_with_plugins

JIRA = {"jira_url": "https://jira.example.test"}


EPIC = {"project_key": "CHEF", "issue_type": "Epic", "summary": "Kitchen helper v1", "description": "Kitchen helper v1 as a local web app."}


CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


PHASE_STATE = {"class": "read_only", "enforced": True, "source": "workflow_definition", "escalation_decision": None}


def _plan(**extra):
    plan = plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0)
    return resolve_turn_tool_surface(plan, capability_type="diagnosis", workflow_id=None, workflow_contract=None,
                                     routing_resolution=None, agent_definition=None, project_config={},
                                     capability_class="read_only", **extra)


# AWS and Kubernetes connectors disable some tools, so the Workspace tool
# policy has rules and the policy filter judges every offered tool, Jira's write tools included.
WORKSPACE_WITH_DENY_RULES = {**JIRA, "connector_policies": {"aws": {"disabled_tools": ["invoke_aws_lambda"]},
                                                            "jira": {"disabled_tools": ["update_jira_ticket"]}}}


async def _offered(state: dict | None, project_config: dict = WORKSPACE_WITH_DENY_RULES) -> set[str]:
    """The tools a turn offers the model: the governed surface through the real catalog, visibility and policy."""
    plan = _plan(chat_connector_writes=bool(state and state.get("chat_connector_writes")))
    context = ToolContext(user_id="u1", project_ids=[], roles=["member"], session_id="s1",
                          project_config=dict(project_config), capability_type="diagnosis",
                          run_capability=dict(state) if state else None)
    definitions = await build_run_context_tool_definitions(
        db=None, tool_context=context, capability_type="diagnosis", include_tools=plan.include_tools,
        tool_allowlist=plan.tool_allowlist, blocked_tools=plan.blocked_tools, agent_definition=None,
        get_all_tools_with_plugins=get_all_tools_with_plugins, filter_tool_definitions=_filter_tool_definitions,
        exclude_tool_definitions=_exclude_tool_definitions)
    return {definition["function"]["name"] for definition in definitions}
