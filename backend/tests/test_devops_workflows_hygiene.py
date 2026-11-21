"""DevOps workflows hygiene: the artifact producers and the tool surface without orchestrator placeholders."""

from __future__ import annotations

from app.services.workflow_checks.evidence import ARTIFACT_PRODUCERS
from app.tools.definitions import get_all_definitions


def test_the_artifact_checks_know_their_producing_tools():
    assert ARTIFACT_PRODUCERS["create_document"] == "document"
    assert ARTIFACT_PRODUCERS["create_presentation"] == "presentation"


def test_the_orchestrator_placeholder_tools_are_off_the_tool_surface():
    names = set(get_all_definitions())
    assert not names & {"delegate_to_child", "wait_for_children", "review_output"}
    assert "spawn_sub_agent" in names
