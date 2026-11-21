"""Immutable Agent Definition revisions.

An ``AgentDefinitionRevision`` is an append-only snapshot of one
:class:`~app.models.agent.agent_definition.AgentDefinition` plus its ordered
steps, taken at the moment an administrator asks for a revision, or by the governed
write boundary on every authored change.

Which of the two the runtime executes is an explicit, configured decision, not a
property of these rows: under ``agent_definition_execution_mode: published`` the
published revision's snapshot is the executed content and the live row supplies only
identity and ownership, while under the named ``draft`` mode the live row is the
authored source. See :mod:`app.services.agent_definition_execution`. The live rows
remain what the Agent Designer edits against and what a restore writes onto.

Immutability contract:

* ``snapshot_json`` and ``checksum`` are written once, at creation, and never
  rewritten. Two snapshots with identical authored content produce the same
  checksum, so content drift between revisions is detectable.
* ``revision_number`` is monotonic per definition and unique
  (``uq_agent_definition_revision_number``).
* Only ``status``, ``validation_json``, ``published_by``, ``published_at``,
  ``approved_by`` and ``approved_at`` ever change after insert, and only while the revision is not yet published.

``status`` is one of ``draft``, ``invalid``, or ``published``. A revision is
published only after validation passes at publish time, so an unvalidated or
failing revision can never become the published contract. Lineage lives in
``restored_from_revision_id``: a revision produced by restoring an earlier
published revision points back at its source.

The snapshot holds only the definition's own authored fields. No connector
credential, provider secret, or framework error text is copied into
``snapshot_json`` or ``validation_json``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
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
from ..json_text import dump_json_dict, safe_json_dict

#: Lifecycle states of a revision. Deliberately minimal: review/eval/approved
#: states and four-eyes approval are separate policy slices.
REVISION_STATUS_DRAFT = "draft"
REVISION_STATUS_INVALID = "invalid"
REVISION_STATUS_PUBLISHED = "published"

REVISION_STATUSES = frozenset(
    {REVISION_STATUS_DRAFT, REVISION_STATUS_INVALID, REVISION_STATUS_PUBLISHED}
)


def uuid_pk() -> str:
    return str(uuid.uuid4())


class AgentDefinitionRevision(Base):
    __tablename__ = "agent_definition_revisions"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "revision_number",
            name="uq_agent_definition_revision_number",
        ),
        Index(
            "ix_agent_definition_revisions_definition_status",
            "definition_id",
            "status",
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    definition_id = Column(
        String(36),
        ForeignKey("agent_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default=REVISION_STATUS_DRAFT)
    #: Hex sha256 over the canonical snapshot form; see
    #: ``app.services.agent_definition_revisions.compute_snapshot_checksum``.
    checksum = Column(String(64), nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False, default="{}")
    #: Last validation verdict, ``NULL`` while the draft has never been validated.
    validation_json = Column(Text, nullable=True)
    restored_from_revision_id = Column(
        String(36),
        ForeignKey("agent_definition_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    published_by = Column(String(36), nullable=True)
    published_at = Column(DateTime, nullable=True)
    #: The second admin of a platform agent publish; ``NULL`` for every other agent.
    approved_by = Column(String(36), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    definition = relationship("AgentDefinition")
    restored_from = relationship("AgentDefinitionRevision", remote_side=[id])

    @property
    def snapshot(self) -> dict[str, Any]:
        return safe_json_dict(self.snapshot_json)

    @snapshot.setter
    def snapshot(self, value: dict[str, Any] | None) -> None:
        self.snapshot_json = dump_json_dict(value)

    @property
    def validation(self) -> dict[str, Any] | None:
        if self.validation_json is None:
            return None
        return safe_json_dict(self.validation_json)

    @validation.setter
    def validation(self, value: dict[str, Any] | None) -> None:
        self.validation_json = None if value is None else dump_json_dict(value)

    @property
    def is_published(self) -> bool:
        return self.status == REVISION_STATUS_PUBLISHED


__all__ = [
    "REVISION_STATUSES",
    "REVISION_STATUS_DRAFT",
    "REVISION_STATUS_INVALID",
    "REVISION_STATUS_PUBLISHED",
    "AgentDefinitionRevision",
]
