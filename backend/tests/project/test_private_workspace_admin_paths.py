"""The admin paths into a private Workspace, each closed.

Admin = the seeded ``admin``; owner = a ``viewer`` with a private session holding ``SECRET-PRIVATE-CONTENT``.
- nobody mints an API key for another person; a password reset tells the person (account recovery itself
  cannot be prevented: an accepted residual risk);
- an admin's GDPR export of the owner leaves the private Workspace out (the owner's own export has it);
- the admin diagnostics tool and session list do not see it;
- session files are not served to an admin;
- no Actions (Tasks) can exist in it;
- no other Workspace can use it as a knowledge source; the admin knowledge views refuse it;
- the cross-session clarification list leaves its questions out;
- the MCP graph tools search only the caller's own Workspaces;
- it gets the default Workspace's policy (model grant, classification, seat rule), kept in line.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Message, Notification, Project, Session, User
from app.services.auth import create_access_token
from app.services.project.private_workspace import ensure_private_workspace, sync_template_policy
from tests.devices.device_support import user_named
from tests.policy_engine_support import grant_role

SECRET = "SECRET-PRIVATE-CONTENT"


async def _setup(db):
    owner = await user_named(db, f"alice-{uuid.uuid4().hex[:6]}")
    await db.commit()
    await grant_role(db, owner.id, "viewer")
    private = await ensure_private_workspace(db, owner)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=private.id, origin="chat", status="active")
    db.add(session)
    await db.flush()
    db.add(Message(session_id=session.id, role="user", content=SECRET))
    await db.commit()
    return owner, private, session


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


@pytest.mark.asyncio
async def test_h1_nobody_mints_an_api_key_for_someone_else_and_a_reset_is_told(client, db, auth_headers):
    owner, _private, _session = await _setup(db)
    owner_id = owner.id
    minted = await client.post(f"/admin/chat/api/panel/users/{owner_id}/api-keys", headers=auth_headers,
                               json={"name": "support"})
    assert minted.status_code == 403 and minted.json()["reason"] == "api_key_for_other_user"
    reset = await client.post(f"/admin/chat/api/panel/users/{owner_id}/reset-password", headers=auth_headers,
                              json={"password": "Review-Pass-123!"})
    assert reset.status_code == 200
    notices = (await db.execute(select(Notification).where(Notification.user_id == owner_id))).scalars().all()
    assert any(notice.type == "account_recovery" for notice in notices)


@pytest.mark.asyncio
async def test_h2_an_admins_gdpr_export_leaves_the_private_workspace_out(client, db, auth_headers):
    owner, _private, _session = await _setup(db)

    async def export(headers) -> bool:
        job = await client.post("/api/v1/data/exports", headers=headers, json={
            "export_type": "user_data_gdpr", "scope_type": "user", "scope_id": owner.id, "format": "zip"})
        assert job.status_code in (200, 201), job.text
        blob = (await client.get(f"/api/v1/data/exports/{job.json()['id']}/download", headers=headers)).content
        archive = zipfile.ZipFile(io.BytesIO(blob))
        return any(SECRET.encode() in archive.read(name) for name in archive.namelist())

    assert await export(auth_headers) is False
    assert await export({"Authorization": f"Bearer {create_access_token(owner.id)}"}) is True


@pytest.mark.asyncio
async def test_h3_the_admin_tools_do_not_see_it(db):
    from app.tools.admin_impl._admin_diagnostics import AdminGetThreadDiagnosticsTool, AdminListSessionsTool
    from app.tools.context import ToolContext

    _owner, _private, session = await _setup(db)
    admin = await _admin(db)
    context = ToolContext(user_id=admin.id, project_ids=[], roles=["admin"], session_id="", project_config={}, db=db)
    out = await AdminGetThreadDiagnosticsTool().execute({"session_id": session.id}, context)
    assert SECRET not in str(out) and "not found" in str(out)
    listed = await AdminListSessionsTool().execute({"limit": 200}, context)
    assert session.id not in str(listed)


@pytest.mark.asyncio
async def test_h4_session_files_are_not_served_to_an_admin(client, db, auth_headers):
    from app.services.session.workspace import ensure_session_workspace_root

    owner, _private, session = await _setup(db)
    root = await ensure_session_workspace_root(db, session, create=True)
    await db.commit()
    target = Path(root) / "uploads" / "note.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SECRET-PRIVATE-FILE")
    refused = await client.get("/chat/api/artifact", params={"path": str(target), "download": "true"},
                               headers=auth_headers)
    assert refused.status_code == 403 and "SECRET-PRIVATE-FILE" not in refused.text
    own = await client.get("/chat/api/artifact", params={"path": str(target), "download": "true"},
                           headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    assert own.status_code == 200 and "SECRET-PRIVATE-FILE" in own.text


@pytest.mark.asyncio
async def test_h5_no_actions_can_exist_in_it(db):
    from app.models.project.task import Task

    owner, private, _session = await _setup(db)
    db.add(Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=private.id, name="my private action", owner_id=owner.id, config={}))
    with pytest.raises(HTTPException) as refused:
        await db.flush()
    assert refused.value.status_code == 409
    await db.rollback()


@pytest.mark.asyncio
async def test_h6_it_is_never_another_workspaces_knowledge_source(client, db, auth_headers):
    from app.services.knowledge_access_policy import load_knowledge_access_policy

    _owner, private, _session = await _setup(db)
    private_id = private.id
    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": f"adm-{uuid.uuid4().hex[:6]}"})
    shared_id = created.json()["id"]
    await client.put(f"/admin/chat/api/panel/projects/{shared_id}/config", headers=auth_headers,
                     json={"central_knowledge_project_ids": [private_id],
                           "knowledge_mounts": [{"source_project_id": private_id}]})
    db.expire_all()
    policy = await load_knowledge_access_policy(db, project_id=shared_id)
    assert private_id not in policy.direct_project_ids
    preview = await client.post("/admin/chat/api/panel/knowledge/retrieval-preview", headers=auth_headers,
                                json={"query": "secret", "project_id": private_id})
    assert preview.status_code == 404
    graph = await client.get("/admin/chat/api/panel/knowledge/entity-graph", headers=auth_headers,
                             params={"project_id": private_id})
    assert graph.status_code == 404


@pytest.mark.asyncio
async def test_h7_the_cross_session_question_list_leaves_it_out(client, db, auth_headers):
    from app.models import ClarificationQuestion

    owner, private, session = await _setup(db)
    db.add(ClarificationQuestion(session_id=session.id, project_id=private.id, question_id="q1",
                                 question_text="SECRET-PRIVATE-QUESTION", status="open", requested_by=owner.id))
    await db.commit()
    listed = await client.get("/api/v1/clarifications", headers=auth_headers)
    assert listed.status_code == 200 and "SECRET-PRIVATE-QUESTION" not in listed.text


@pytest.mark.asyncio
async def test_h8_the_graph_tools_search_only_the_callers_own_workspaces(db):
    from app.services.mcp_entity_graph_tools import mcp_entity_search

    _owner, private, _session = await _setup(db)
    admin = await _admin(db)
    out = await mcp_entity_search(db, user=admin, arguments={"project_id": private.id, "query": "x"})
    assert out == {"error": "Workspace not found or not accessible"}


@pytest.mark.asyncio
async def test_m3_it_gets_the_default_workspaces_policy_and_keeps_it_in_line(db):
    from app.services.project.default_workspace import set_default_workspace

    admin = await _admin(db)
    template = Project(id=str(uuid.uuid4()), name=f"default-{uuid.uuid4().hex[:6]}", config={
        "model_policy": {"allowed_aliases": ["gemma-4-31b"]}, "agent_gateway_policy": {"seat": "allowed"},
        "role_access_assignments": [{"role_id": "x"}]})
    db.add(template)
    await db.flush()
    await set_default_workspace(db, project_id=template.id, actor_id=admin.id)
    owner, private, _session = await _setup(db)
    assert private.config["model_policy"] == {"allowed_aliases": ["gemma-4-31b"]}
    assert private.config["agent_gateway_policy"] == {"seat": "allowed"}
    assert "role_access_assignments" not in private.config  # access rules are never copied
    template.config = {**template.config, "model_policy": {"allowed_aliases": ["gemma-4-31b", "claude-opus-5-5"]}}
    await db.flush()
    assert await sync_template_policy(db, private) is True
    assert private.config["model_policy"]["allowed_aliases"] == ["gemma-4-31b", "claude-opus-5-5"]
    assert await sync_template_policy(db, private) is False
    assert owner.id == private.owner_user_id


# --- further admin paths ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_only_its_creator_reads_a_gdpr_export(client, db, auth_headers):
    owner, _private, _session = await _setup(db)
    own = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
    job = await client.post("/api/v1/data/exports", headers=own, json={
        "export_type": "user_data_gdpr", "scope_type": "user", "scope_id": owner.id, "format": "zip"})
    job_id = job.json()["id"]
    assert job_id not in (await client.get("/api/v1/data/exports", headers=auth_headers)).text
    assert (await client.get(f"/api/v1/data/exports/{job_id}/download", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/v1/data/exports/{job_id}/download", headers=own)).status_code == 200


@pytest.mark.asyncio
async def test_b3_the_admin_update_user_tool_tells_the_person_and_audits(db):
    from app.models import AuditLog
    from app.tools.admin_impl._admin_user_accounts import AdminUpdateUserTool
    from app.tools.context import ToolContext

    owner, _private, _session = await _setup(db)
    owner_id, username = owner.id, owner.username
    admin = await _admin(db)
    context = ToolContext(user_id=admin.id, project_ids=[], roles=["admin"], session_id="", project_config={}, db=db)
    await AdminUpdateUserTool().execute({"user": username, "identifier": username, "user_id": owner_id,
                                         "password": "Silent-Pass-123!", "email": f"{username}@new.invalid"}, context)
    await db.commit()
    notices = {notice.type for notice in (await db.execute(
        select(Notification).where(Notification.user_id == owner_id))).scalars()}
    assert notices == {"account_recovery"}
    audits = {row.action for row in (await db.execute(
        select(AuditLog).where(AuditLog.resource_id == owner_id))).scalars()}
    assert {"admin.user.password_reset", "admin.user.updated"} <= audits


@pytest.mark.asyncio
async def test_b4_routes_naming_a_private_session_answer_404_to_an_admin(client, db, auth_headers):
    _owner, _private, session = await _setup(db)
    generated = await client.post(f"/api/v1/flows/generate-from-session/{session.id}", headers=auth_headers, json={})
    assert generated.status_code == 404 and SECRET not in generated.text
    setup = await client.get(f"/api/v1/effective-setup/sessions/{session.id}", headers=auth_headers)
    assert setup.status_code == 404
    replay = await client.post("/api/v1/workflow-checks/replay", headers=auth_headers,
                               json={"session_id": session.id, "workflow_key": "x"})
    assert replay.status_code == 404


@pytest.mark.asyncio
async def test_b2_no_channel_runs_in_a_private_workspace(client, db, auth_headers):
    _owner, private, _session = await _setup(db)
    created = await client.post("/admin/chat/api/panel/channels", headers=auth_headers, json={
        "name": f"teams-{uuid.uuid4().hex[:6]}", "plugin_id": "teams", "project_id": private.id, "config": {}})
    assert created.status_code == 409 and created.json()["reason"] == "private_workspace_has_no_channels"


@pytest.mark.asyncio
async def test_agent_runs_never_use_someone_elses_private_workspace(db):
    from app.agent.core.context.run_context import prepare_agent_run

    _owner, private, session = await _setup(db)
    admin = await _admin(db)
    with pytest.raises(PermissionError):
        await prepare_agent_run(db=db, session_id=session.id, user_message="hi", user_id=admin.id,
                                project_id=private.id, agent_type="chat", runtime_target_id=None,
                                thinking_level=None, agent_definition=None, parent_session_id=None, sub_agent_depth=0,
                                workspace_root="/tmp", resolve_model_context_cap=None,
                                resolve_control_plane_runtimes_func=None, filter_tool_definitions=None,
                                exclude_tool_definitions=None, trim_messages_to_budget=None)


@pytest.mark.asyncio
async def test_no_agent_chains_in_a_private_workspace(db):
    from app.models import AgentChainTemplate

    owner, private, _session = await _setup(db)
    db.add(AgentChainTemplate(id=str(uuid.uuid4()), name="mine", project_id=private.id, created_by=owner.id,
                              steps_json=[]))
    with pytest.raises(HTTPException) as refused:
        await db.flush()
    assert refused.value.status_code == 409
    await db.rollback()


@pytest.mark.asyncio
async def test_m3_the_sync_keeps_creation_defaults_and_the_owners_narrowing(db):
    from app.services.project.default_workspace import set_default_workspace

    admin = await _admin(db)
    template = Project(id=str(uuid.uuid4()), name=f"default-{uuid.uuid4().hex[:6]}", config={
        "model_policy": {"allowed_aliases": ["gemma-4-31b", "claude-opus-5-5"]},
        "knowledge_episode_policy": {"accept_session_episodes": True}})
    db.add(template)
    await db.flush()
    await set_default_workspace(db, project_id=template.id, actor_id=admin.id)
    _owner, private, _session = await _setup(db)
    assert "trace_capture" in private.config and "knowledge_episode_policy" not in private.config
    private.config = {**private.config, "model_policy": {"allowed_aliases": ["gemma-4-31b"]}}
    await db.flush()
    assert await sync_template_policy(db, private) is False  # the default did not change: the narrowing stays
    assert private.config["model_policy"] == {"allowed_aliases": ["gemma-4-31b"]}
    template.config = {**template.config, "runtime_cost_limits": {"per_turn_usd": 1}}
    await db.flush()
    assert await sync_template_policy(db, private) is True  # an admin changed the defaults: they apply
    assert "trace_capture" in private.config and private.config["runtime_cost_limits"] == {"per_turn_usd": 1}
