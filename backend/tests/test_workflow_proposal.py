"""Contract tests for workflow proposals: the platform proposes, the user confirms."""

from __future__ import annotations

import pytest

from tests.workflow_proposal_support import (  # noqa: F401
    MESSAGE,
    _answer,
    _profile,
    _project,
    _resolve,
    proposal_model,
)

pytestmark = pytest.mark.workflow_proposals

PHASED_WORKFLOW = "incident-analysis"










@pytest.mark.asyncio
async def test_explicit_workflow_key_always_wins_without_a_proposal_call(db, proposal_model):  # noqa: F811
    provider = proposal_model(_answer(PHASED_WORKFLOW))

    explicit = await _resolve(db, workflow_key=PHASED_WORKFLOW)
    no_workflow = await _resolve(db, workflow_key="none")

    assert provider.calls == []
    assert explicit["status"] == "needs_confirmation" and explicit["workflow_id"] is None
    assert explicit["workflow_proposal"]["reason_code"] == "explicit_phased_selection"
    assert explicit["workflow_proposal"]["workflow_key"] == PHASED_WORKFLOW
    assert no_workflow["workflow_proposal"]["reason_code"] == "user_selected_no_workflow"
    assert no_workflow["workflow_id"] is None
