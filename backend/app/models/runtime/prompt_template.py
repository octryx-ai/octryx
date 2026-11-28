"""Governed prompt catalog records: templates per scope and their append-only versions."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from .governed_revision import (
    DIGEST_LENGTH,
    REVISION_STATES,
    ImmutableRevisionError,
    in_list,
    install_immutability_guard,
)

PROMPT_SCOPE_GLOBAL = "global"
PROMPT_SCOPE_WORKSPACE = "workspace"
# A workflow's own texts (scope id: the flow key), between global and Workspace.
PROMPT_SCOPE_WORKFLOW = "workflow"
PROMPT_SCOPE_TYPES: tuple[str, ...] = (PROMPT_SCOPE_GLOBAL, PROMPT_SCOPE_WORKSPACE, PROMPT_SCOPE_WORKFLOW)

PROMPT_SOURCE_SEED = "seed"
PROMPT_SOURCE_ADMIN = "admin"
PROMPT_VERSION_SOURCES: tuple[str, ...] = (PROMPT_SOURCE_SEED, PROMPT_SOURCE_ADMIN)

PROMPT_KEY_LENGTH = 120
PROMPT_SCOPE_KEY_LENGTH = 80

_SCOPE_SHAPE_CHECK = (
    "(scope_type = 'global' AND scope_id IS NULL) OR (scope_type <> 'global' AND scope_id IS NOT NULL)"
)
_PUBLISHED_CHECK = "state NOT IN ('published') OR published_at IS NOT NULL"
_IMMUTABLE_COLUMNS = frozenset({"body", "digest", "template_id", "version", "source"})


def uuid_pk() -> str:
    return str(uuid.uuid4())


class PromptTemplate(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_scope__ = ("scope_type", (PROMPT_SCOPE_WORKSPACE,), "scope_id")
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("key", "scope_key", name="uq_prompt_templates_key_scope"),
        CheckConstraint(in_list("scope_type", PROMPT_SCOPE_TYPES), name="ck_prompt_templates_scope_type"),
        CheckConstraint(_SCOPE_SHAPE_CHECK, name="ck_prompt_templates_scope_shape"),
        Index("ix_prompt_templates_scope", "scope_type", "scope_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(PROMPT_KEY_LENGTH), nullable=False, index=True)
    scope_type = Column(String(24), nullable=False)
    scope_id = Column(String(36), nullable=True)
    scope_key = Column(String(PROMPT_SCOPE_KEY_LENGTH), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)

    versions = relationship(
        "PromptTemplateVersion",
        back_populates="template",
        order_by="PromptTemplateVersion.version.asc()",
        passive_deletes=True,
    )


class PromptTemplateVersion(Base):
    __tablename__ = "prompt_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_prompt_template_versions_number"),
        CheckConstraint(in_list("state", REVISION_STATES), name="ck_prompt_template_versions_state"),
        CheckConstraint(in_list("source", PROMPT_VERSION_SOURCES), name="ck_prompt_template_versions_source"),
        CheckConstraint("version >= 1", name="ck_prompt_template_versions_version"),
        CheckConstraint(_PUBLISHED_CHECK, name="ck_prompt_template_versions_published"),
        Index("ix_prompt_template_versions_template_state", "template_id", "state"),
        Index(
            "uq_prompt_template_versions_one_published",
            "template_id",
            unique=True,
            sqlite_where=text("state = 'published'"),
            postgresql_where=text("state = 'published'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    template_id = Column(String(36), ForeignKey("prompt_templates.id", ondelete="RESTRICT"), nullable=False)
    version = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    source = Column(String(24), nullable=False)
    body = Column(Text, nullable=False)
    digest = Column(String(DIGEST_LENGTH), nullable=False, index=True)
    change_note = Column(String(500), nullable=False)
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

    template = relationship("PromptTemplate", back_populates="versions")


def _guard_immutable_body(_mapper, _connection, target) -> None:
    # A version's text, digest and identity never change: an edit is a new version.
    state = inspect(target)
    if any(state.attrs[name].history.has_changes() for name in _IMMUTABLE_COLUMNS):
        raise ImmutableRevisionError("prompt_version_body_immutable")


install_immutability_guard(PromptTemplateVersion)
event.listen(PromptTemplateVersion, "before_update", _guard_immutable_body)


__all__ = [
    "PROMPT_KEY_LENGTH",
    "PROMPT_SCOPE_WORKFLOW",
    "PROMPT_SCOPE_GLOBAL",
    "PROMPT_SCOPE_TYPES",
    "PROMPT_SCOPE_WORKSPACE",
    "PROMPT_SOURCE_ADMIN",
    "PROMPT_SOURCE_SEED",
    "PROMPT_VERSION_SOURCES",
    "PromptTemplate",
    "PromptTemplateVersion",
]
