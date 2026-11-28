from __future__ import annotations

import pytest

from app.models import Project
from app.services.agent_gateway.engine_policy import set_workspace_engines
from app.services.agent_gateway.policy import load_workspace_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.devices.workspace_policy import set_workspace_device_runs
from tests.agent_gateway.seat_presence_support import _workspace
from tests.knowledge_evidence_seed_support import seed_member

BASELINE_RULES = [rule["id"] for rule in BASELINE_POLICY["tool_rules"]]
BASELINE_DENY = tuple(BASELINE_POLICY["client_permissions"]["deny"])
OWN_VERIFICATION = {"test_command_prefixes": [["pytest"]], "change_tools": ["Edit"]}


async def _saved_alone(db, setting: str, own_policy: dict | None):
    workspace_id = await _workspace(db, policy=own_policy)
    admin = await seed_member(db, workspace_id=workspace_id)
    project = await db.get(Project, workspace_id)
    if setting == "engines":
        await set_workspace_engines(db, project=project, value={"allowed": ["codex"], "default": "codex"},
                                    actor_id=admin)
    else:
        await set_workspace_device_runs(db, project=project, patch={"enabled": True}, actor_id=admin)
    await db.commit()
    return (await load_workspace_policy(db, workspace_id)).policy


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["engines", "device_runs"])
async def test_a_setting_saved_alone_keeps_the_baseline_rules(db, setting):
    policy = await _saved_alone(db, setting, None)
    assert [rule.id for rule in policy.tool_rules] == BASELINE_RULES
    assert policy.deny_permissions == BASELINE_DENY
    assert policy.daily_budget_usd == BASELINE_POLICY["session_budget"]["per_user_daily_usd"]
    assert policy.source == "baseline"


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["engines", "device_runs"])
async def test_a_setting_saved_beside_an_own_verification_keeps_both(db, setting):
    policy = await _saved_alone(db, setting, {"verification": OWN_VERIFICATION})
    assert policy.verification is not None and policy.verification.test_command_prefixes == (("pytest",),)
    assert [rule.id for rule in policy.tool_rules] == BASELINE_RULES
    assert policy.source == "workspace"


@pytest.mark.asyncio
async def test_an_own_empty_rule_list_stays_empty(db):
    workspace_id = await _workspace(db, policy={"tool_rules": []})
    policy = (await load_workspace_policy(db, workspace_id)).policy
    assert policy.tool_rules == () and policy.deny_permissions == BASELINE_DENY
