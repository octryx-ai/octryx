"""Device-run policy: off by default, platform kill switch, Workspace opt-in with profiles, the matrix
rule (on at every level, D10), seat only where the Workspace's seat decision allows it (D2), Cedar
``run_on_device`` equal to the legacy decision, and kill switches that stop running turns."""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import AuditLog, ContentConversationState, DeviceJob, Project
from app.services.content_routing.conversation_state import CHAT_CONVERSATION
from app.services.data_classification.policy_rules import LOCKED_RULES, LevelRules, default_rules
from app.services.devices import device_policy
from app.services.devices.device_policy import builtin_device_decision
from app.services.devices.device_runs_keys import DEFAULTS
from app.services.devices.hub import device_hub
from app.services.model_gateway.data_policy.classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    DATA_CLASSIFICATION_ORDER,
    WorkspaceDataClassification,
)
from app.services.policy_engine.device_point import device_query
from app.services.policy_engine.entities import principal_entities
from app.services.policy_engine.points import POINT_DEVICE_DISPATCH
from app.services.policy_engine.shadow import OUTCOME_MATCH, decision_counters, shadow_decision
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    device_with_grant,
    enable_device_runs,
    member_with_headers,
)

FOLDER = "/home/sample/src"


class Connected(RecordingConnection):
    seat_login = True


@pytest.fixture(autouse=True)
def _empty_hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _send(client, headers, device, session, **target):
    body = {"prompt": "Run the tests", "session_id": session.id,
            "execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed",
                                 **target}}
    response = await client.post("/chat/api/send", json=body, headers=headers)
    return response.status_code, (response.json().get("detail") or {}).get("reason")


async def _setup(db, auth_user, profiles=("governed", "seat")):
    device, _ = await device_with_grant(db, auth_user, profiles=list(profiles))
    device_hub._connections[device.id] = Connected(device.id)
    return device, await chat_session(db, auth_user)


@pytest.mark.asyncio
async def test_device_runs_are_on_by_default_and_a_workspace_that_switched_them_off_stays_off(client, db, auth_headers,
                                                                                               auth_user):
    """Default policy: without any Workspace setting a member's chat reaches their own device; a Workspace
    whose admin stored ``enabled: false`` keeps it off and nothing reaches the device."""
    assert DEFAULTS["enabled"] is True
    device, session = await _setup(db, auth_user)
    assert (await _send(client, auth_headers, device, session))[0] == 200
    await enable_device_runs(db, enabled=False)
    other = await chat_session(db, auth_user)
    assert await _send(client, auth_headers, device, other) == (409, "device_runs_disabled")
    assert [job.session_id for job in (await db.execute(select(DeviceJob))).scalars().all()] == [session.id]


@pytest.mark.asyncio
async def test_workspace_opt_in_is_for_workspace_admins_and_audited(client, db, auth_headers, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    _member, member_headers = await member_with_headers(client, db, "other-member")
    url = f"/api/v1/workspaces/{project.id}/agent-gateway/device-runs"
    current = (await client.get(url, headers=auth_headers)).json()
    assert current["enabled"] is True
    assert (await client.put(url, json={"enabled": True}, headers=member_headers)).status_code in (403, 404)
    invalid = await client.put(url, json={"enabled": "yes"}, headers=auth_headers)
    assert invalid.status_code == 400 and invalid.json()["reason"] == "invalid_flag"
    assert (await client.put(url, json={"approval_timeout_s": 5}, headers=auth_headers)).status_code == 400
    saved = await client.put(url, json={"enabled": False, "allowed_profiles": ["governed"]}, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is False and saved.json()["allowed_profiles"] == ["governed"]
    assert "device-runs-disabled" in saved.json()["cedar_preview"]
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "admin.agent_gateway.device_runs_updated")))
    assert audit.scalars().first().details["changes"] == {"enabled": False, "allowed_profiles": ["governed"]}


@pytest.mark.asyncio
async def test_profiles_and_seat_follow_the_workspace(client, db, auth_headers, auth_user):
    device, session = await _setup(db, auth_user)
    await enable_device_runs(db, allowed_profiles=["governed"])
    assert await _send(client, auth_headers, device, session, profile="seat") == (403, "device_profile_not_allowed")
    await enable_device_runs(db)
    # Seat is selectable (D2) but the Workspace's seat decision still decides (an unclassified Workspace here).
    assert await _send(client, auth_headers, device, session, profile="seat") == (
        403, "seat_classification_unresolved")
    assert await _send(client, auth_headers, device, session, folder="/etc") == (403, "folder_not_allowlisted")
    assert (await _send(client, auth_headers, device, session))[0] == 200


@pytest.mark.asyncio
async def test_a_thread_with_sensitive_content_refuses_seat_only_when_the_team_opted_in(client, db, auth_headers,
                                                                                        auth_user):
    device, session = await _setup(db, auth_user)
    await enable_device_runs(db)
    db.add(ContentConversationState(session_id=session.id, conversation_key=CHAT_CONVERSATION, categories=["pii"],
                                    detectors={"email": 1}))
    await db.commit()
    # Default: sensitive content alone does not refuse the seat; the seat decision goes on as usual.
    assert await _send(client, auth_headers, device, session, profile="seat") != (409, "content_requires_governed")
    await enable_device_runs(db, sensitive_content_requires_governed=True)
    await db.commit()
    assert await _send(client, auth_headers, device, session, profile="seat") == (409, "content_requires_governed")
    assert (await _send(client, auth_headers, device, session))[0] == 200


@pytest.mark.asyncio
async def test_the_matrix_rule_turns_a_level_off(client, db, auth_headers, auth_user, monkeypatch):
    device, session = await _setup(db, auth_user)
    await enable_device_runs(db)

    async def level_off(db_arg, workspace_id, level):  # the level's rules with the Workspace's overrides (S4)
        return LevelRules(seat_allowed=False, device_runs_allowed=level != "confidential")

    async def confidential(db_arg, *, project_id):
        return WorkspaceDataClassification("confidential", CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")

    monkeypatch.setattr(device_policy, "workspace_rules_by_id", level_off)
    monkeypatch.setattr(device_policy, "resolve_workspace_data_classification", confidential)
    assert await _send(client, auth_headers, device, session) == (403, "device_runs_classification")
    assert all(default_rules(level).device_runs_allowed for level in DATA_CLASSIFICATION_ORDER)
    assert LOCKED_RULES.device_runs_allowed is False


@pytest.mark.asyncio
async def test_the_platform_kill_switch_refuses_and_stops_running_turns(client, db, auth_headers, auth_user):
    _member, member_headers = await member_with_headers(client, db, "other-member")
    device, session = await _setup(db, auth_user)
    await enable_device_runs(db)
    assert (await _send(client, auth_headers, device, session))[0] == 200
    job = (await db.execute(select(DeviceJob))).scalar_one()
    job.turn_state, job.status = "accepted", "running"
    await db.flush()
    assert (await client.put("/api/v1/admin/device-runs", json={"enabled": False},
                             headers=member_headers)).status_code == 403
    assert (await client.put("/api/v1/admin/device-runs", json={"enabled": False},
                             headers=auth_headers)).json() == {"enabled": False}
    assert job.stop_state == "pending"
    other = await chat_session(db, auth_user)
    assert await _send(client, auth_headers, device, other) == (403, "device_runs_platform_disabled")
    await client.put("/api/v1/admin/device-runs", json={"enabled": True}, headers=auth_headers)
    assert (await client.get("/api/v1/admin/device-runs", headers=auth_headers)).json() == {"enabled": True}


@pytest.mark.asyncio
async def test_turning_the_workspace_off_stops_its_running_turns(client, db, auth_headers, auth_user):
    project = await enable_device_runs(db)
    device, session = await _setup(db, auth_user)
    await _send(client, auth_headers, device, session)
    job = (await db.execute(select(DeviceJob))).scalar_one()
    job.turn_state, job.status = "accepted", "running"
    await db.flush()
    response = await client.put(f"/api/v1/workspaces/{project.id}/agent-gateway/device-runs", json={"enabled": False},
                                headers=auth_headers)
    assert response.status_code == 200
    assert job.stop_state == "pending"


def test_cedar_run_on_device_decides_like_the_legacy_gate():
    device = SimpleNamespace(id="dev_x", owner_user_id="u1", os="linux", profiles=["governed", "seat"], status="active")
    principal = principal_entities("u1")
    sections = [None, {"enabled": False}, {"enabled": True}, {"enabled": True, "allowed_profiles": ["governed"]},
                {"enabled": True, "allowed_profiles": ["seat"]}]
    count = 0
    for stored, level, allowed, profile, folder in itertools.product(
        sections, [*DATA_CLASSIFICATION_ORDER, None], (True, False), ("governed", "seat"), (True, False)
    ):
        raw = {"device_runs": stored} if stored is not None else {}
        rules = LevelRules(seat_allowed=False, device_runs_allowed=allowed) if level else None
        classification = (WorkspaceDataClassification(level, CLASSIFICATION_SOURCE_PROJECT_CONFIG, "") if level
                          else None)
        legacy = builtin_device_decision({**DEFAULTS, **(stored or {})}, rules, profile=profile,
                                        folder_allowlisted=folder)
        comparison = shadow_decision(POINT_DEVICE_DISPATCH, legacy, lambda: device_query(
            workspace_id="ws", classification=classification, rules=rules, raw_policy=raw, device=device,
            profile=profile, folder_allowlisted=folder, principal=principal))
        assert comparison is None or comparison.outcome == OUTCOME_MATCH, (stored, level, allowed, profile, folder)
        count += 1
    counters = decision_counters().get(POINT_DEVICE_DISPATCH, {})
    assert {outcome: n for outcome, n in counters.items() if n and outcome != OUTCOME_MATCH} == {}
    assert counters.get(OUTCOME_MATCH, 0) == count
