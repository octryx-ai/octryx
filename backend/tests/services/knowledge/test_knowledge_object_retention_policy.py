"""Retention policy defaults, the recorded legal hold and the bound checks of an explicit policy."""

from __future__ import annotations

import pytest

from app.models.project.knowledge_object_retention import RETENTION_MODE_REPORT_ONLY
from app.services.knowledge.retention.errors import InvalidRetentionRequestError
from app.services.knowledge.retention.policy import load_retention_policy, set_retention_policy
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.knowledge_object_retention_support import _set_policy

# --- policy -----------------------------------------------------------------


async def test_no_policy_row_means_the_report_only_default(db):
    workspace_id = await seed_workspace(db)
    policy = await load_retention_policy(db, workspace_id)

    assert policy.explicit is False
    assert policy.mode == RETENTION_MODE_REPORT_ONLY
    assert policy.legal_hold is False


async def test_an_explicit_policy_records_its_bounds_and_legal_hold(db):
    workspace_id = await seed_workspace(db)
    await _set_policy(db, workspace_id, min_age_hours=48, legal_hold=True)

    policy = await load_retention_policy(db, workspace_id)
    assert policy.explicit is True and policy.mode == RETENTION_MODE_REPORT_ONLY
    assert (policy.min_object_age_hours, policy.legal_hold) == (48, True)


async def test_policy_values_outside_their_bounds_fail_closed(db):
    workspace_id = await seed_workspace(db)
    refused = (
        {"mode": "delete_approved"},
        {"mode": "delete_everything"},
        {"mode": RETENTION_MODE_REPORT_ONLY, "min_object_age_hours": 0},
        {"mode": RETENTION_MODE_REPORT_ONLY, "min_object_age_hours": 9000},
        {"mode": RETENTION_MODE_REPORT_ONLY, "min_object_age_hours": True},
        {"mode": RETENTION_MODE_REPORT_ONLY, "legal_hold": "yes"},
    )
    for overrides in refused:
        with pytest.raises(InvalidRetentionRequestError):
            await set_retention_policy(db, project_id=workspace_id, updated_by=None, **overrides)
    assert (await load_retention_policy(db, workspace_id)).explicit is False
