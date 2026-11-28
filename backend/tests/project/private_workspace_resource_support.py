"""One record of every Workspace-bound resource family that admins address by id, in one Workspace."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select

from app.models import (
    Approval,
    ConnectorWatcher,
    ConnectorWatcherEvent,
    ConnectorWatcherRule,
    ConnectorWatcherRuleDecision,
    Session,
    User,
    WorkCodingPipelineConfig,
    WorkflowRun,
    WorkItemSyncConfig,
    WorkItemWorkflowDefinition,
    WorkRepositoryProfile,
)
from app.services.project.private_workspace import ensure_private_workspace
from app.time_utils import utc_now
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace

OWNER_MARKER = "resource-id-owner"


@dataclass(frozen=True)
class Resources:
    workspace_id: str
    run_id: str
    approval_id: str
    problem_key: str
    pipeline_config_id: str
    repository_profile_id: str
    watcher_id: str
    workflow_id: str
    watcher_event_id: str
    watcher_rule_id: str
    watcher_decision_id: str

    def unknown(self) -> Resources:
        return Resources(workspace_id=str(uuid.uuid4()), run_id=str(uuid.uuid4()), approval_id=str(uuid.uuid4()),
                         problem_key=f"intake:{uuid.uuid4()}:failed", pipeline_config_id=str(uuid.uuid4()),
                         repository_profile_id=str(uuid.uuid4()), watcher_id=str(uuid.uuid4()),
                         workflow_id=str(uuid.uuid4()), watcher_event_id=str(uuid.uuid4()),
                         watcher_rule_id=str(uuid.uuid4()), watcher_decision_id=str(uuid.uuid4()))


async def insert_run(db, workspace_id: str, requester_id: str, *, context: dict | None = None) -> str:
    # A Core insert skips the ORM guard that keeps runs out of private Workspaces: the access rules must hold on
    # their own.
    run_id = str(uuid.uuid4())
    await db.execute(insert(WorkflowRun.__table__).values(
        id=run_id, project_id=workspace_id, workflow_kind="phased", workflow_key="resource-id-flow",
        title=f"{OWNER_MARKER} run", requested_by=requester_id, status="waiting", context=context or {}))
    await db.commit()
    return run_id


async def seed_resources(db, workspace_id: str, user: User) -> Resources:
    session = Session(id=str(uuid.uuid4()), user_id=user.id, project_id=workspace_id, origin="chat")
    db.add(session)
    await db.flush()
    approval = Approval(session_id=session.id, requested_by=user.id, action="tool:shell", status="pending",
                        workspace_id=workspace_id, reason=f"{OWNER_MARKER} approval")
    intake = WorkItemSyncConfig(name=f"{OWNER_MARKER} intake", created_by=user.id, project_id=workspace_id,
                                last_sync_status="failed", last_sync_at=utc_now())
    config = WorkCodingPipelineConfig(name=f"{OWNER_MARKER} pipeline", created_by=user.id, project_id=workspace_id)
    profile = WorkRepositoryProfile(name=f"{OWNER_MARKER} profile", created_by=user.id, project_id=workspace_id)
    watcher = ConnectorWatcher(connector_name="jira", name=f"{OWNER_MARKER} watcher", created_by=user.id,
                               project_id=workspace_id)
    workflow = WorkItemWorkflowDefinition(name=f"{OWNER_MARKER} workflow", created_by=user.id,
                                          project_id=workspace_id)
    db.add_all([approval, intake, config, profile, watcher, workflow])
    await db.flush()
    event = ConnectorWatcherEvent(watcher_id=watcher.id, connector_name="jira", project_id=workspace_id,
                                  payload_hash=uuid.uuid4().hex)
    rule = ConnectorWatcherRule(name=f"{OWNER_MARKER} rule", created_by=user.id, project_id=workspace_id)
    db.add_all([event, rule])
    await db.flush()
    decision = ConnectorWatcherRuleDecision(rule_id=rule.id, event_id=event.id, watcher_id=watcher.id,
                                            project_id=workspace_id)
    db.add(decision)
    await db.flush()
    run_id = await insert_run(db, workspace_id, user.id)
    return Resources(workspace_id=workspace_id, run_id=run_id, approval_id=approval.id,
                     problem_key=f"intake:{intake.id}:failed", pipeline_config_id=config.id,
                     repository_profile_id=profile.id, watcher_id=watcher.id, workflow_id=workflow.id,
                     watcher_event_id=event.id, watcher_rule_id=rule.id, watcher_decision_id=decision.id)


async def owner_admin_and_resources(db) -> tuple[User, User, dict[str, Resources]]:
    owner = await user_named(db, f"{OWNER_MARKER}-{uuid.uuid4().hex[:6]}")
    foreign = await ensure_private_workspace(db, owner)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    own = await ensure_private_workspace(db, admin)
    shared = await seed_workspace(db)
    await db.commit()
    return owner, admin, {"private": await seed_resources(db, foreign.id, owner),
                          "shared": await seed_resources(db, shared, admin),
                          "own": await seed_resources(db, own.id, admin)}


__all__ = ["OWNER_MARKER", "Resources", "insert_run", "owner_admin_and_resources", "seed_resources"]
