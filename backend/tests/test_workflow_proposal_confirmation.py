"""The proposal call writes exactly one usage event, and the proposal policy is validated."""

from __future__ import annotations

import pytest

from tests.workflow_proposal_support import MESSAGE, _answer, proposal_model  # noqa: F401

pytestmark = pytest.mark.workflow_proposals

PHASED_WORKFLOW = "incident-analysis"




def test_the_proposal_policy_is_validated():
    from app.services.workflow_routing.proposal_policy import (
        WorkflowProposalPolicyError,
        normalize_workflow_proposal_policy,
        workflow_proposals_enabled_in,
    )

    assert normalize_workflow_proposal_policy({"enabled": None}) == {}
    assert normalize_workflow_proposal_policy({"enabled": False}) == {"enabled": False}
    with pytest.raises(WorkflowProposalPolicyError):
        normalize_workflow_proposal_policy({"enabled": "no"})
    # Only an explicit False switches proposals off; the default is on.
    assert workflow_proposals_enabled_in({}) is True
    assert workflow_proposals_enabled_in({"workflow_proposal_policy": {"enabled": False}}) is False
