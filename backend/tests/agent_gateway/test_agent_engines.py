"""Coding engine per platform, Workspace and person: Claude Code or Codex.

- without any setting, Claude Code applies and both engines are allowed;
- the platform admin sets the platform default; a Workspace admin overrides it and limits the allowed engines;
- a person chooses only among the Workspace's allowed engines; a choice the Workspace no longer allows falls back
  to the Workspace default;
- every write is audited; members cannot change the Workspace setting;
- the launcher reads the same with its gateway login;
- a device job keeps the engine of its first offer, and a job that continues another job's session takes its engine.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, DeviceJob, User
from app.services.agent_gateway.engine_policy import (
    AUDIT_PERSON,
    AUDIT_PLATFORM,
    AUDIT_WORKSPACE,
    resolve,
    set_person_choice,
)
from app.services.devices.job_engine import job_engine
from app.services.devices.job_offer import offer_body
from tests.agent_gateway.seat_presence_support import _bearer, _gateway_headers, _workspace
from tests.devices.device_support import chat_session, keyed_device
from tests.knowledge_evidence_seed_support import seed_member

PLATFORM = "/api/v1/admin/agent-engine"
WORKSPACE = "/api/v1/workspaces/{}/agent-gateway/engines"
LAUNCHER = "/api/v1/agent-gateway/engine?workspace_id={}"


async def _setup(db):
    workspace = await _workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member", username="engine-member")
    admin = await seed_member(db, workspace_id=workspace, role="admin", username="engine-admin")
    await db.commit()
    return workspace, member, admin


async def _audits(db, action):
    return (await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()


def test_resolution_order():
    both = {"allowed": ["claude_code", "codex"]}
    assert resolve(platform="claude_code", section=None, choice=None).engine == "claude_code"
    assert resolve(platform="codex", section=None, choice=None).source == "platform"
    assert resolve(platform="claude_code", section={**both, "default": "codex"}, choice=None).engine == "codex"
    chosen = resolve(platform="claude_code", section=both, choice="codex")
    assert (chosen.engine, chosen.source) == ("codex", "person")
    # the Workspace no longer allows the person's choice: its default applies, the choice stays visible
    only_claude = resolve(platform="codex", section={"allowed": ["claude_code"]}, choice="codex")
    assert (only_claude.engine, only_claude.source, only_claude.person_choice) == ("claude_code", "workspace", "codex")


@pytest.mark.asyncio
async def test_defaults_platform_workspace_and_person_with_audit(client, db, auth_headers):
    workspace, member, admin = await _setup(db)
    shown = (await client.get(WORKSPACE.format(workspace), headers=await _bearer(member))).json()
    assert shown["effective"]["engine"] == "claude_code" and shown["effective"]["allowed"] == ["claude_code", "codex"]
    assert shown["source"] == "default" and shown["can_edit"] is False

    # platform admin: Codex by default for the whole platform
    refused = await client.put(PLATFORM, json={"default": "codex"}, headers=await _bearer(member))
    assert refused.status_code == 403
    assert (await client.put(PLATFORM, json={"default": "gpt"}, headers=auth_headers)).status_code == 422
    assert (await client.put(PLATFORM, json={"default": "codex"}, headers=auth_headers)).json()["default"] == "codex"
    shown = (await client.get(WORKSPACE.format(workspace), headers=await _bearer(member))).json()
    assert (shown["effective"]["engine"], shown["effective"]["source"]) == ("codex", "platform")

    # Workspace admin: back to Claude Code here, and Codex not allowed; a member cannot change it
    assert (await client.put(WORKSPACE.format(workspace), json={"allowed": ["claude_code"]},
                             headers=await _bearer(member))).status_code == 403
    bad = await client.put(WORKSPACE.format(workspace), json={"allowed": ["claude_code"], "default": "codex"},
                           headers=await _bearer(admin))
    assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["code"] == "default_not_allowed"
    saved = await client.put(WORKSPACE.format(workspace), json={"allowed": ["claude_code"]},
                             headers=await _bearer(admin))
    assert saved.status_code == 200, saved.text
    assert saved.json()["effective"]["engine"] == "claude_code" and saved.json()["source"] == "workspace"

    # person: Codex is not allowed in this Workspace; once it is, the member's own choice applies
    me = WORKSPACE.format(workspace) + "/me"
    denied = await client.put(me, json={"engine": "codex"}, headers=await _bearer(member))
    assert denied.status_code == 422
    assert denied.json()["detail"]["errors"][0]["code"] == "engine_not_allowed_in_workspace"
    await client.put(WORKSPACE.format(workspace), json={"allowed": ["claude_code", "codex"], "default": "claude_code"},
                     headers=await _bearer(admin))
    chosen = await client.put(me, json={"engine": "codex"}, headers=await _bearer(member))
    assert (chosen.json()["effective"]["engine"], chosen.json()["effective"]["source"]) == ("codex", "person")
    cleared = await client.put(me, json={"engine": None}, headers=await _bearer(member))
    assert cleared.json()["effective"]["engine"] == "claude_code"

    assert len(await _audits(db, AUDIT_PLATFORM)) == 1
    assert [row.details["after"] for row in await _audits(db, AUDIT_WORKSPACE)] == [
        {"allowed": ["claude_code"]}, {"allowed": ["claude_code", "codex"], "default": "claude_code"}]
    assert [row.details["after"] for row in await _audits(db, AUDIT_PERSON)] == ["codex", None]


@pytest.mark.asyncio
async def test_launcher_reads_the_effective_engine_with_its_login(client, db):
    workspace, member, admin = await _setup(db)
    await client.put(WORKSPACE.format(workspace), json={"allowed": ["codex"]}, headers=await _bearer(admin))
    headers = await _gateway_headers(db, member, workspace)
    answer = await client.get(LAUNCHER.format(workspace), headers=headers)
    assert answer.status_code == 200, answer.text
    assert answer.json()["engine"] == "codex" and answer.json()["allowed"] == ["codex"]
    assert (await client.get(LAUNCHER.format("not-mine"), headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_a_job_keeps_its_engine_and_a_continued_session_takes_its_jobs_engine(client, db):
    workspace, member, _admin = await _setup(db)
    user = await db.get(User, member)
    device, _private, _token = await keyed_device(db, user)
    thread = await chat_session(db, user)
    await set_person_choice(db, user_id=member, engine="codex")

    def job(profile: str = "governed", **extra) -> DeviceJob:
        return DeviceJob(owner_user_id=member, workspace_id=workspace, folder="/w", profile=profile,
                         device_id=device.id, session_id=thread.id, **extra)

    first = job()
    assert await job_engine(db, first) == "codex"
    assert offer_body(first, limits={}, engine=first.engine)["engine"] == "codex"
    # the person switches back to Claude Code: the job keeps Codex (its session cannot move engines)
    await set_person_choice(db, user_id=member, engine="claude_code")
    assert await job_engine(db, first) == "codex"

    # the next story continues the first job's Codex session: Codex, whatever the person chose since
    first.claude_session_id = "codex-thread-1"
    db.add(first)
    await db.flush()
    assert await job_engine(db, job(resume_claude_session_id="codex-thread-1")) == "codex"
    # the epic chain gives the next story's job the epic's session as its own: still the session's engine
    assert await job_engine(db, job(claude_session_id="codex-thread-1")) == "codex"
    # a story that only resumed the epic's thread (its own session never reported) still names its engine
    resumed = job(resume_claude_session_id="codex-thread-2")
    resumed.engine = "codex"
    db.add(resumed)
    await db.flush()
    assert await job_engine(db, job(claude_session_id="codex-thread-2")) == "codex"
    # a session no job knows (a Mac session continued from the phone) is Claude Code; a fresh job follows the
    # person's choice
    assert await job_engine(db, job(claude_session_id="mac-only-session")) == "claude_code"
    await set_person_choice(db, user_id=member, engine="codex")
    assert await job_engine(db, job(resume_claude_session_id="fork:mac-session")) == "claude_code"
    assert await job_engine(db, job(profile="local:work")) == "claude_code"
    await set_person_choice(db, user_id=member, engine="claude_code")
    assert await job_engine(db, job()) == "claude_code"
    assert "engine" not in offer_body(job(), limits={})
