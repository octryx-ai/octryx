"""octryx run UX, step 1: a session started for a Work item follows its active run from launch, else gets a proposal."""

from __future__ import annotations

import uuid

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.workflow_runs.octryx import launch
from app.services.workflow_runs.records import active_run_for_session, new_chat_session, start_run
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import _fix_definition

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _gateway(db, user, workspace_id: str, work_item_key: str = ""):
    identity = GatewayIdentity(user=user, grant_id="gw", oauth_client_id="octryx", workspace_id=workspace_id,
                               session_key=str(uuid.uuid4()), work_item_key=work_item_key, workflow_run_id="")
    return await get_or_create_gateway_session(db, identity)


async def _item(db, workspace_id: str, key: str) -> WorkItem:
    item = WorkItem(source_type="jira", source_instance="t", source_key=key, title="Totals round wrong",
                    project_id=workspace_id)
    db.add(item)
    await db.flush()
    return item


def _proposal(monkeypatch, *, key: str, status: str = "needs_confirmation", change_capable: bool = False) -> list[str]:
    asked: list[str] = []

    async def fake(db, *, user_message, project_id):
        asked.append(user_message)
        return {"workflow_proposal": {"version": 1, "status": status, "reason_code": "x", "workflow_key": key,
                                      "workflow_title": key, "confidence": "high", "reason": "fits",
                                      "change_capable": change_capable}}

    monkeypatch.setattr("app.services.workflow_routing.proposal.resolve_workflow_proposal_for_turn", fake)
    monkeypatch.setattr("app.services.workflow_routing.proposal.workflow_proposal_of",
                        lambda resolution: resolution["workflow_proposal"])
    return asked


@pytest.mark.asyncio
async def test_launch_attaches_to_the_items_active_run_only_for_a_person_who_may_act(db):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    item = await _item(db, workspace_id, "PAY-7")
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _fix_definition()),
                          project_id=workspace_id, work_item_id=item.id,
                          session=await new_chat_session(db, admin, workspace_id))
    gateway = await _gateway(db, admin, workspace_id, "PAY-7")
    answer = await launch.launch_answer(db, session=gateway, user=admin, workspace_id=workspace_id,
                                        work_item_key="PAY-7")
    assert answer["workflow_run_attach"]["state"] == "attached"
    assert answer["workflow_run"]["run"]["id"] == run.id and answer["workflow_run"]["phase"]["node_id"] == "fix"
    assert (await active_run_for_session(db, gateway.id)).id == run.id

    member = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    other = await _gateway(db, member, workspace_id, "PAY-7")
    refused = await launch.launch_answer(db, session=other, user=member, workspace_id=workspace_id,
                                         work_item_key="PAY-7")
    assert refused == {"workflow_run_attach": {"state": "denied", "reason": "run_read_only",
                                               "message": refused["workflow_run_attach"]["message"]}}
    assert await active_run_for_session(db, other.id) is None
    unknown = await launch.launch_answer(db, session=other, user=member, workspace_id=workspace_id,
                                         work_item_key="NOPE-1")
    assert unknown["workflow_run_attach"]["reason"] == "work_item_unknown"
    assert await launch.launch_answer(db, session=other, user=member, workspace_id=workspace_id,
                                      work_item_key="") == {}
    assert (await launch.prompt_answer(db, session=gateway, workspace_id=workspace_id, work_item_key="PAY-7",
                                       prompt="go on"))["workflow_run"]["run"]["id"] == run.id


@pytest.mark.asyncio
async def test_a_phased_proposal_is_only_proposed_never_started_and_asked_once(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    await _item(db, workspace_id, "PAY-8")
    key = await publish_phased(db, _fix_definition())
    asked = _proposal(monkeypatch, key=key)
    gateway = await _gateway(db, admin, workspace_id, "PAY-8")
    assert (await launch.launch_answer(db, session=gateway, user=admin, workspace_id=workspace_id,
                                       work_item_key="PAY-8"))["workflow_run_attach"]["state"] == "no_active_run"
    first = await launch.prompt_answer(db, session=gateway, workspace_id=workspace_id, work_item_key="PAY-8",
                                       prompt="fix the rounding")
    proposal = first["workflow_proposal"]
    assert (proposal["state"], proposal["phased"]) == ("proposed", True)
    assert proposal["next"] == {"tool": "workflow_select", "arguments": {"workflow_key": key, "work_item": "PAY-8"}}
    assert "PAY-8" in asked[0] and "fix the rounding" in asked[0]
    assert await active_run_for_session(db, gateway.id) is None
    assert await launch.prompt_answer(db, session=gateway, workspace_id=workspace_id, work_item_key="PAY-8",
                                      prompt="again") == {}
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_a_session_without_a_work_item_is_untouched(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)

    asked = _proposal(monkeypatch, key="whatever")
    plain = await _gateway(db, admin, workspace_id)
    assert await launch.prompt_answer(db, session=plain, workspace_id=workspace_id, work_item_key="",
                                      prompt="hi") == {}
    assert asked == [] and dict(plain.metadata_ or {}).get(launch.PROPOSAL_METADATA) is None


@pytest.mark.asyncio
async def test_a_launch_never_takes_the_run_from_another_session_and_analyze_gets_no_proposal(db, monkeypatch):
    from app.services.work_item_analysis.seat_session import ITEM_METADATA, PURPOSE_ANALYSIS, PURPOSE_METADATA

    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    item = await _item(db, workspace_id, "PAY-10")
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _fix_definition()),
                          project_id=workspace_id, work_item_id=item.id,
                          session=await new_chat_session(db, admin, workspace_id))
    working = await _gateway(db, admin, workspace_id, "PAY-10")
    await launch.launch_answer(db, session=working, user=admin, workspace_id=workspace_id, work_item_key="PAY-10")
    second = await _gateway(db, admin, workspace_id, "PAY-10")
    refused = await launch.launch_answer(db, session=second, user=admin, workspace_id=workspace_id,
                                         work_item_key="PAY-10")
    assert refused["workflow_run_attach"]["reason"] == "run_followed_elsewhere" and "workflow_run" not in refused
    assert (await active_run_for_session(db, working.id)).id == run.id
    assert await active_run_for_session(db, second.id) is None
    from app.services.workflow_runs.octryx.attach import attach

    await attach(db, gateway_session=second, user=admin, workspace_id=workspace_id, run=run)
    assert (await active_run_for_session(db, second.id)).id == run.id

    asked = _proposal(monkeypatch, key="whatever")
    analysis = await _gateway(db, admin, workspace_id, "PAY-10")
    analysis.metadata_ = {**dict(analysis.metadata_ or {}), PURPOSE_METADATA: PURPOSE_ANALYSIS, ITEM_METADATA: item.id}
    assert await launch.prompt_answer(db, session=analysis, workspace_id=workspace_id, work_item_key="PAY-10",
                                      prompt="analyze") == {}
    assert asked == []


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
