"""Only a chat turn may write through connectors: the chat surface offers the write tools after the governed set, and workspace policy rules do not hide them."""

from __future__ import annotations

from app.services.run_capability.declared import capability_from_run_profile
from app.services.run_capability.resolution import decide_run_capability


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




