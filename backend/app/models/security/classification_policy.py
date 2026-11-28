"""Governed classification policy: its versions and the classification levels."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now
from ..runtime.governed_revision import (
    REVISION_STATES,
    in_list,
    install_immutability_guard,
    published_requires_approval_check,
)

CLASSIFICATION_DIGEST_LENGTH = 71


def _uuid() -> str:
    return str(uuid.uuid4())


class ClassificationPolicyVersion(Base):
    __tablename__ = "classification_policy_versions"
    __table_args__ = (
        CheckConstraint(in_list("state", REVISION_STATES), name="ck_classification_policy_versions_state"),
        CheckConstraint("version >= 1", name="ck_classification_policy_versions_version"),
        CheckConstraint(published_requires_approval_check(), name="ck_classification_policy_versions_published"),
        Index("ix_classification_policy_versions_state", "state"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    version = Column(Integer, nullable=False, unique=True)
    state = Column(String(16), nullable=False)
    content = Column(JSON, nullable=False)
    digest = Column(String(CLASSIFICATION_DIGEST_LENGTH), nullable=False)
    note = Column(Text, nullable=True)
    base_version = Column(Integer, nullable=True)
    test_report = Column(JSON, nullable=True)
    # The change lines against the version it was drafted from (``policy_preview.change_lines``), kept for history.
    changes = Column(JSON, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    retired_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    retired_at = Column(DateTime, nullable=True)


install_immutability_guard(ClassificationPolicyVersion)


class DataClassificationLevel(Base):
    """One classification level, built in or added by an admin."""

    __tablename__ = "data_classification_levels"
    __table_args__ = (CheckConstraint("rank >= 1", name="ck_data_classification_levels_rank"),)

    key = Column(String(30), primary_key=True)
    rank = Column(Integer, nullable=False, unique=True)
    label = Column(String(60), nullable=False)
    color = Column(String(20), nullable=False, default="custom")
    description = Column(Text, nullable=True)
    models_allowed = Column(Boolean, nullable=False, default=True)
    builtin = Column(Boolean, nullable=False, default=False)
    retired_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["CLASSIFICATION_DIGEST_LENGTH", "ClassificationPolicyVersion", "DataClassificationLevel"]
