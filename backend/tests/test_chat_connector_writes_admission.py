"""Only a chat turn may write through connectors: the chat surface offers the write tools after the governed set, and workspace policy rules do not hide them."""

from __future__ import annotations

import pytest

from app.services.run_capability.chat_writes import chat_connector_write_tool_names
from app.services.run_capability.declared import capability_from_run_profile
from app.services.run_capability.resolution import decide_run_capability
from tests.chat_connector_writes_support import CHAT_STATE, PHASE_STATE, _offered, _plan


def _decide(**overrides):
    inputs = {"routing_resolution": {"source": "none"}, "requested_agent_type": "chat",
              "requested_mode_capability": "diagnosis", **overrides}
    return decide_run_capability(**inputs)


def test_only_a_chat_turn_may_write_through_connectors_and_it_stays_read_only_otherwise():
    chat = _decide()
    assert (chat.capability_class, chat.source, chat.chat_connector_writes) == ("read_only", "chat_default", True)
    assert chat.tool_context_state()["chat_connector_writes"] is True
    # The recorded profile carries it to the turn's tool context, never into a declaration.
    recorded = capability_from_run_profile({"capability": chat.to_metadata()})
    assert recorded.tool_context_state()["chat_connector_writes"] is True
    assert "chat_connector_writes" not in recorded.to_metadata()

    phase = _decide(routing_resolution={"source": "db", "status": "matched", "selection_source": "workflow_run",
                                        "workflow_contract": {"capability_class": "read_only"}})
    sub_agent = _decide(parent_capability_class="read_only")
    assert phase.chat_connector_writes is False and sub_agent.chat_connector_writes is False


def test_the_chat_surface_offers_the_connector_write_tools_after_the_governed_set():
    chat = _plan(chat_connector_writes=True)
    assert {"create_jira_ticket", "add_jira_comment", "update_jira_ticket", "create_bitbucket_pull_request"} <= set(
        chat.tool_allowlist)
    assert chat.tool_allowlist[0] == "select_workflow", "the governed set keeps its priority order first"
    assert not set(_plan().tool_allowlist) & set(chat_connector_write_tool_names())
    # The one confirmation per request comes with the writes, and only with them.
    assert "propose_write_plan" in chat.tool_allowlist and "propose_write_plan" not in _plan().tool_allowlist
    # Only connector writes: no workspace edits or pushes through this door.
    assert "write_workspace_file" not in chat.tool_allowlist and "http_request" not in chat.tool_allowlist


@pytest.mark.asyncio
async def test_a_chat_is_offered_create_jira_ticket_although_the_workspace_policy_has_rules():
    """The write tools are on the surface and the high-risk rule is waived at dispatch, so the offering filter must
    waive it too, or the model never sees create_jira_ticket and creates a stray work item instead."""
    chat = await _offered(CHAT_STATE)
    assert {"create_jira_ticket", "add_jira_comment", "get_jira_ticket", "propose_write_plan"} <= chat
    assert "update_jira_ticket" not in chat, "a Workspace deny rule still refuses a chat write"
    phase = await _offered(PHASE_STATE)
    assert "get_jira_ticket" in phase and "create_jira_ticket" not in phase, "only a chat turn gets the waiver"
