"""The answer style of a selected ``knowledge_request`` contract comes from its definition's
``knowledge_query_style``, never from the prompt; an unsupported one is ``needs_configuration``."""

from __future__ import annotations

import pytest

from app.services.workflow_contracts.registry import build_task_workflow_contract


def _explicit_contract(prompt: str, configured: dict) -> dict:
    return build_task_workflow_contract(prompt, request_analysis={"workflow_contract": configured})


@pytest.mark.parametrize(
    ("configured_style", "state", "style"),
    [
        (None, "resolved", "lookup"),
        ("definition", "resolved", "definition"),
        ("summary", "needs_configuration", "lookup"),
    ],
)
def test_the_knowledge_answer_style_comes_from_the_definition(configured_style, state, style):
    configured = {"workflow_id": "knowledge_request"}
    if configured_style:
        configured["knowledge_query_style"] = configured_style
    contract = _explicit_contract("What is Report Builder?", configured)

    assert contract["knowledge_query_style"] == style
    assert contract["workflow_variant"]["state"] == state
    assert "managed_workflow_profile" not in contract
