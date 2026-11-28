"""Setup guide status: seven steps in order, each done / open / attention from stored rows only."""

import uuid

import pytest
from sqlalchemy import update

from app.models import (
    AgentDefinition,
    ConnectorNamedConnection,
    IdentityProvider,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
    KnowledgeSourceSyncRun,
    Project,
    ProjectUserRoleAssignment,
    User,
)
from app.services.setup_guide import onboarding_status as module
from app.services.setup_guide.onboarding_status import STEP_ORDER, onboarding_status
from tests.factories import make_project

pytestmark = pytest.mark.asyncio


async def _isolate(db, monkeypatch, *, models_ready=False, providers=0, allowed_model=False):
    # Every other active Workspace is set aside so the platform steps read only what a test adds.
    await db.execute(update(Project).values(is_active=False))
    await db.execute(update(IdentityProvider).values(is_active=False))

    async def guide(_db):
        return {"ready": models_ready, "stats": {"active_provider_count": providers},
                "steps": [{"key": "default", "title": "Default is ready", "blocking": True, "status": "pending",
                           "detail": "Claude Sonnet 5.5 is #1 but not cleared for data."}]}

    async def models(_db, _project_id):
        return {"models": [{"allowed": allowed_model, "used_in": ["chat"]}]}

    monkeypatch.setattr(module, "get_setup_guide_status", guide)
    monkeypatch.setattr(module, "read_models", models)


async def _workspace(db, name="ux-first-run"):
    return (await make_project(db, name=name, is_system=False)).id


async def _user(db):
    user = User(id=str(uuid.uuid4()), username=f"u-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@x.test",
                password_hash="x", is_active=True)
    db.add(user)
    await db.flush()
    return user.id


def _by_key(status):
    return {step["key"]: step for step in status["steps"]}


async def test_nothing_set_up_every_step_is_open_in_order(db, monkeypatch):
    await _isolate(db, monkeypatch)
    status = await onboarding_status(db, workspace_id=None)
    assert [step["key"] for step in status["steps"]] == list(STEP_ORDER)
    assert {step["status"] for step in status["steps"]} == {"open"}
    assert status["done_count"] == 0 and status["total"] == 7 and status["workspace"] is None
    steps = _by_key(status)
    assert [steps[key]["scope"] for key in STEP_ORDER] == [
        "platform", "workspace", "workspace", "platform", "platform", "workspace", "workspace"]
    assert steps["sso"]["recommended"] and steps["roles"]["recommended"] and not steps["models"]["recommended"]


async def test_platform_steps_flip_on_their_own_rows(db, monkeypatch):
    await _isolate(db, monkeypatch, models_ready=True, providers=1)
    workspace_id = await _workspace(db)
    db.add(IdentityProvider(name="Entra", provider_type="oidc", is_active=True))
    await db.flush()
    steps = _by_key(await onboarding_status(db, workspace_id=workspace_id))
    assert steps["workspace"]["status"] == "done"
    assert steps["models"]["status"] == "done"
    assert steps["sso"]["status"] == "done"


async def test_a_provider_whose_default_is_not_ready_needs_attention(db, monkeypatch):
    await _isolate(db, monkeypatch, models_ready=False, providers=1)
    steps = _by_key(await onboarding_status(db, workspace_id=None))
    assert steps["models"]["status"] == "attention"
    # The reason names the model and the problem; the button opens Default & fallback.
    assert steps["models"]["reason"].startswith("Claude Sonnet 5.5 is #1 but not cleared for data.")
    assert steps["models"]["target"] == "modelOrder"


async def test_connectors_are_done_only_with_a_successful_test(db, monkeypatch):
    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db)
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="jira", project_id=workspace_id, scope_key=workspace_id,
                                   name="Jira", config={}, bound_scopes=[], last_test=None)
    db.add(row)
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["connectors"]["status"] == "attention"
    row.last_test = {"ok": False, "at": None, "summary": "401"}
    await db.flush()
    failed = _by_key(await onboarding_status(db, workspace_id=workspace_id))["connectors"]
    assert failed["status"] == "attention" and "failed" in failed["reason"]
    row.last_test = {"ok": True, "at": None, "summary": ""}
    await db.flush()
    done = _by_key(await onboarding_status(db, workspace_id=workspace_id))["connectors"]
    assert (done["status"], done["scope"]) == ("done", "workspace")


async def test_a_shared_connection_counts_as_a_platform_fact(db, monkeypatch):
    # A Workspace without its own connection is not reported as having one.
    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db)
    db.add(ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="jira", project_id=None, scope_key="global",
                                    name="Jira (shared)", config={}, bound_scopes=[], last_test={"ok": True}))
    await db.flush()
    shared = _by_key(await onboarding_status(db, workspace_id=workspace_id))["connectors"]
    assert (shared["status"], shared["scope"]) == ("done", "platform")
    assert "shared connection" in shared["reason"]


async def test_sources_follow_the_last_sync(db, monkeypatch):
    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db)
    connector = KnowledgeSourceConnector(project_id=workspace_id, connector_key="confluence-rt", kind="confluence",
                                         scope={}, products=[], cursor={})
    db.add(connector)
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "attention"
    run = KnowledgeSourceSyncRun(connector_id=connector.id, project_id=workspace_id, state="failed", report={}, outcomes=[])
    db.add(run)
    await db.flush()
    connector.last_run_id = run.id
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "attention"
    run.state = "completed"
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "done"


async def test_a_snapshot_source_that_serves_items_has_synced_without_a_run(db, monkeypatch):
    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db)
    connector = KnowledgeSourceConnector(project_id=workspace_id, connector_key="repo-snapshot", kind="git_repository",
                                         scope={}, products=[], cursor={})
    db.add(connector)
    await db.flush()
    db.add(KnowledgeSourceSyncItem(connector_id=connector.id, project_id=workspace_id, external_id="README.md",
                                   source_key="repo-snapshot:README.md", source_id=None, state="withheld",
                                   last_outcome="withheld"))
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "attention"
    db.add(KnowledgeSourceSyncItem(connector_id=connector.id, project_id=workspace_id, external_id="docs/a.md",
                                   source_key="repo-snapshot:docs/a.md", source_id=str(uuid.uuid4()), state="served",
                                   last_outcome="created"))
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "done"


async def test_roles_need_a_person_who_is_not_a_platform_admin(db, monkeypatch):
    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db)
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["roles"]["status"] == "open"
    db.add(ProjectUserRoleAssignment(user_id=await _user(db), project_id=workspace_id, role_name="member"))
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["roles"]["status"] == "done"


async def test_agents_need_a_usable_agent_and_an_allowed_model(db, monkeypatch):
    await _isolate(db, monkeypatch, allowed_model=False)
    workspace_id = await _workspace(db)
    db.add(AgentDefinition(owner_id=await _user(db), project_id=workspace_id, name="Assistant", is_active=True))
    await db.flush()
    steps = _by_key(await onboarding_status(db, workspace_id=workspace_id))
    assert steps["agents"]["status"] == "attention" and "model" in steps["agents"]["reason"]
    await _isolate(db, monkeypatch, allowed_model=True)
    await db.execute(update(Project).where(Project.id == workspace_id).values(is_active=True))
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["agents"]["status"] == "done"


async def test_an_indexed_repository_counts_as_a_knowledge_source(db, monkeypatch):
    from app.models.runtime.code_intelligence import CodeRepository
    from app.time_utils import utc_now

    await _isolate(db, monkeypatch)
    workspace_id = await _workspace(db, name="Demo")
    repository = CodeRepository(project_id=workspace_id, name="public-demo", repo_root="/tmp/demo", provider="github")
    db.add(repository)
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "open"
    repository.last_indexed_at = utc_now()
    await db.flush()
    assert _by_key(await onboarding_status(db, workspace_id=workspace_id))["sources"]["status"] == "done"
