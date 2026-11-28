"""What the matrix page and the Workspace Policy view are told — the editable alias list, who may edit,
and where an inherited daily budget comes from."""

from __future__ import annotations

import pytest

from tests.knowledge_evidence_seed_support import seed_member
from tests.model_gateway.conftest import ALIAS
from tests.support.classification_policy_matrix_support import ROUTE, _admin_id, _bearer, _gateway, _summary, _workspace

pytestmark = pytest.mark.without_baseline_runtime


@pytest.mark.asyncio
async def test_the_matrix_lists_the_gateway_aliases_for_the_editor(client, db):
    headers = await _bearer(await _admin_id(db))
    before = (await client.get(ROUTE, headers=headers)).json()
    await _gateway(db)

    read = (await client.get(ROUTE, headers=headers)).json()

    assert before["model_aliases"] == []
    assert read["model_aliases"] == [ALIAS]


@pytest.mark.asyncio
async def test_the_policy_summary_can_edit_follows_the_matrix_platform_admin_rule(client, db):
    workspace_id = await _workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    workspace_admin = await seed_member(db, workspace_id=workspace_id, role="admin")
    await db.commit()

    owner_view = (await client.get(_summary(workspace_id), headers=await _bearer(owner))).json()
    admin_view = (await client.get(_summary(workspace_id), headers=await _bearer(workspace_admin))).json()
    platform = await client.get(_summary(workspace_id), headers=await _bearer(await _admin_id(db)))
    matrix = (await client.get(ROUTE, headers=await _bearer(owner))).json()

    assert owner_view["can_edit"] is False is admin_view["can_edit"] is matrix["can_edit"]
    assert platform.status_code == 200 and platform.json()["can_edit"] is True


@pytest.mark.asyncio
async def test_a_daily_budget_the_workspace_policy_does_not_set_is_the_default(client, db):
    workspace_id = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()

    body = (await client.get(_summary(workspace_id), headers=await _bearer(member))).json()

    assert body["budgets"]["per_user_daily_usd"] == {"value_usd": 200.0, "source": "default"}
