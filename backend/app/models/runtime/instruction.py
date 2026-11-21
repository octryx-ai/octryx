"""Instructions: guidance the agent reads, bound explicitly.

An instruction has a **scope** (``global``, ``workspace``, ``agent``) and a **binding**: always in its
scope, or only when the workflow ``workflow_key`` is selected. There is no scoring and no keyword path:
a turn gets exactly the published instructions whose scope and binding match it
(``services/instructions/resolve.py``). Versions are append-only; publishing needs a four-eyes review and
an accepted conflict check (``services/instructions/lifecycle.py``).
"""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now

INSTRUCTION_SCOPE_GLOBAL = "global"
INSTRUCTION_SCOPE_WORKSPACE = "workspace"
INSTRUCTION_SCOPE_AGENT = "agent"
INSTRUCTION_SCOPES: tuple[str, ...] = (INSTRUCTION_SCOPE_GLOBAL, INSTRUCTION_SCOPE_WORKSPACE, INSTRUCTION_SCOPE_AGENT)
INSTRUCTION_BINDING_ALWAYS = "always"
INSTRUCTION_BINDING_WORKFLOW = "workflow"
INSTRUCTION_BINDING_ON_REQUEST = "on_request"
INSTRUCTION_BINDINGS: tuple[str, ...] = (
    INSTRUCTION_BINDING_ALWAYS, INSTRUCTION_BINDING_WORKFLOW, INSTRUCTION_BINDING_ON_REQUEST,
)
INSTRUCTION_STATUS_ACTIVE = "active"
INSTRUCTION_STATUS_RETIRED = "retired"
INSTRUCTION_VERSION_STATES: tuple[str, ...] = ("draft", "in_review", "published", "retired")
INSTRUCTION_SOURCES: tuple[str, ...] = ("admin", "seed")


def uuid_pk() -> str:
    return str(uuid.uuid4())


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Instruction(Base):
    __tablename__ = "instructions"
    __table_args__ = (
        UniqueConstraint("key", "scope_type", "scope_id", name="uq_instructions_key_scope"),
        CheckConstraint(_in("scope_type", INSTRUCTION_SCOPES), name="ck_instructions_scope_type"),
        CheckConstraint(_in("binding", INSTRUCTION_BINDINGS), name="ck_instructions_binding"),
        CheckConstraint(
            "(binding = 'workflow' AND workflow_key IS NOT NULL) OR (binding <> 'workflow' AND workflow_key IS NULL)",
            name="ck_instructions_binding_shape",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR (scope_type <> 'global' AND scope_id IS NOT NULL)",
            name="ck_instructions_scope_shape",
        ),
        Index("ix_instructions_scope", "scope_type", "scope_id"),
        Index("ix_instructions_workflow_key", "workflow_key"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(120), nullable=False)
    title = Column(String(220), nullable=False)
    scope_type = Column(String(16), nullable=False)
    # The Workspace id or the agent definition id; empty for global.
    scope_id = Column(String(36), nullable=True)
    # always (every turn in the scope) | workflow (only when ``workflow_key`` is selected) | on_request (never
    # injected; the model reads it by exact key with ``instruction_get``).
    binding = Column(String(16), nullable=False, default=INSTRUCTION_BINDING_ALWAYS)
    workflow_key = Column(String(180), nullable=True)
    status = Column(String(16), nullable=False, default=INSTRUCTION_STATUS_ACTIVE)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)

    versions = relationship(
        "InstructionVersion", back_populates="instruction", order_by="InstructionVersion.version",
        cascade="all, delete-orphan",
    )


class InstructionVersion(Base):
    __tablename__ = "instruction_versions"
    __table_args__ = (
        UniqueConstraint("instruction_id", "version", name="uq_instruction_versions_version"),
        CheckConstraint(_in("state", INSTRUCTION_VERSION_STATES), name="ck_instruction_versions_state"),
        CheckConstraint(_in("source", INSTRUCTION_SOURCES), name="ck_instruction_versions_source"),
        CheckConstraint("state <> 'published' OR published_at IS NOT NULL", name="ck_instruction_versions_published"),
        Index("ix_instruction_versions_state", "instruction_id", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    instruction_id = Column(String(36), ForeignKey("instructions.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    digest = Column(String(80), nullable=False)
    token_estimate = Column(Integer, nullable=False, default=0)
    state = Column(String(16), nullable=False)
    source = Column(String(16), nullable=False, default="admin")
    change_note = Column(String(500), nullable=False, default="")
    # The conflict check at submit (closed findings) and whether the submitter accepted them.
    findings_json = Column(JSON, nullable=False, default=list)
    findings_accepted = Column(Integer, nullable=False, default=0)
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    retired_at = Column(DateTime, nullable=True)

    instruction = relationship("Instruction", back_populates="versions")


__all__ = [
    "INSTRUCTION_BINDINGS",
    "INSTRUCTION_BINDING_ALWAYS",
    "INSTRUCTION_BINDING_ON_REQUEST",
    "INSTRUCTION_BINDING_WORKFLOW",
    "INSTRUCTION_SCOPES",
    "INSTRUCTION_SCOPE_AGENT",
    "INSTRUCTION_SCOPE_GLOBAL",
    "INSTRUCTION_SCOPE_WORKSPACE",
    "INSTRUCTION_STATUS_ACTIVE",
    "INSTRUCTION_STATUS_RETIRED",
    "Instruction",
    "InstructionVersion",
]
