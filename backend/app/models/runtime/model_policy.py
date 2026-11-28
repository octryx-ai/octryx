"""Model Policy registry: a Workspace-scoped, ordered list of model aliases and the capabilities each needs."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from .governed_revision import (
    DIGEST_LENGTH,
    REGISTRY_STATUSES,
    REVISION_STATES,
    in_list,
    install_immutability_guard,
    published_requires_approval_check,
)


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ModelPolicy(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
    __tablename__ = "model_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_model_policies_workspace_name"),
        CheckConstraint(in_list("status", REGISTRY_STATUSES), name="ck_model_policies_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    status = Column(String(16), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)

    revisions = relationship(
        "ModelPolicyRevision",
        back_populates="policy",
        order_by="ModelPolicyRevision.revision.asc()",
        passive_deletes=True,
    )


class ModelPolicyRevision(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"policy_id": "model_policies"}
    __tablename__ = "model_policy_revisions"
    __table_args__ = (
        UniqueConstraint("policy_id", "revision", name="uq_model_policy_revisions_number"),
        CheckConstraint(in_list("state", REVISION_STATES), name="ck_model_policy_revisions_state"),
        CheckConstraint("revision >= 1", name="ck_model_policy_revisions_revision"),
        CheckConstraint(published_requires_approval_check(), name="ck_model_policy_revisions_published"),
        Index("ix_model_policy_revisions_policy_state", "policy_id", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    policy_id = Column(String(36), ForeignKey("model_policies.id", ondelete="RESTRICT"), nullable=False)
    revision = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    entries_json = Column(JSON, nullable=False)
    digest = Column(String(DIGEST_LENGTH), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    retired_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    retired_at = Column(DateTime, nullable=True)

    policy = relationship("ModelPolicy", back_populates="revisions")


install_immutability_guard(ModelPolicyRevision)


__all__ = ["ModelPolicy", "ModelPolicyRevision"]
