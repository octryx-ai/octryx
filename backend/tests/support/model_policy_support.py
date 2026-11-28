"""Shared builders for the Model Policy registry tests: a Workspace with roles and a published policy row."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Approval, ModelPolicy, ModelPolicyRevision, Project, User
from app.services.model_policy.entries import entries_digest
from app.time_utils import utc_now
from tests.agent_definition_revision_fixtures import make_member, make_project, make_user

MODEL_POLICY_NAME = "standard-models"
LOOPBACK_ORIGINS = "http://localhost:8090,http://127.0.0.1:8090"


async def publish_model_policy(
    db: AsyncSession, project: Project, user: User, name: str, *, aliases: tuple[str, ...] = ("fast-small",)
) -> ModelPolicy:
    entries = [{"alias": alias, "required_capabilities": []} for alias in aliases]
    approval = Approval(requested_by=user.id, approved_by=user.id, action="fixture", status="approved")
    policy = ModelPolicy(workspace_id=project.id, name=name, status="active", created_by=user.id)
    db.add_all([approval, policy])
    await db.flush()
    db.add(
        ModelPolicyRevision(
            policy_id=policy.id,
            revision=1,
            state="published",
            entries_json=entries,
            digest=entries_digest(entries),
            created_by=user.id,
            approval_id=approval.id,
            published_by=user.id,
            published_at=utc_now(),
        )
    )
    await db.flush()
    return policy


@dataclass(frozen=True)
class SeededWorkspace:
    project: Project
    author: User
    reviewer: User
    member: User


async def seed_workspace(db: AsyncSession) -> SeededWorkspace:
    project = await make_project(db)
    author = await make_user(db, label="author")
    reviewer = await make_user(db, label="reviewer")
    member = await make_user(db, label="member")
    await make_member(db, author, project, "owner")
    await make_member(db, reviewer, project, "admin")
    await make_member(db, member, project, "member")
    await publish_model_policy(db, project, author, MODEL_POLICY_NAME)
    return SeededWorkspace(project, author, reviewer, member)


def four_eyes_settings(*, dev_self_approval: bool) -> Settings:
    return Settings.model_construct(
        four_eyes_dev_self_approval=dev_self_approval,
        runtime_profile="local",
        cors_allowed_origins=LOOPBACK_ORIGINS,
    )


async def decide_approval(db: AsyncSession, approval_id: str, approver: User) -> Approval:
    approval = await db.get(Approval, approval_id)
    approval.status = "approved"
    approval.approved_by = approver.id
    approval.resolved_at = utc_now()
    await db.flush()
    return approval


__all__ = [
    "MODEL_POLICY_NAME",
    "SeededWorkspace",
    "decide_approval",
    "four_eyes_settings",
    "publish_model_policy",
    "seed_workspace",
]
