"""The Memory lobe's ledger: what sessions taught the platform.

Memory is experience, not source evidence. An item says what was decided, agreed or learned in a
session, by whom and how trustworthy it is; it never carries a ``source_url`` and is never cited as a
source. Items live in one Workspace and do not flow through Workspace bindings.

- **scope**: ``user`` items are personal and visible only to ``owner_user_id``; ``workspace`` items
  (optionally about one ``product``) are visible to the Workspace's members.
- **author_class** drives trust: ``human_stated`` (a person said it), ``model_inferred`` (the agent
  concluded it), ``verified`` (checked against source evidence).
- **state**: ``observed`` (unreviewed) and ``confirmed`` are recallable; ``superseded`` (replaced by a
  correction, see ``supersedes_id``), ``contradicted``, ``expired`` and ``forgotten`` are not.
  ``promoted`` is reserved for the explicit promotion into Knowledge.
- **forgetting is real**: a forgotten item keeps only its id, scope, state and who forgot it when;
  ``text`` and ``content_hash`` are erased.
- **provenance**: the session, the turn (the run's request id) and the author, plus ``created_at``.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text

from ...db import Base
from ...time_utils import utc_now


class MemoryScope(StrEnum):
    USER = "user"
    WORKSPACE = "workspace"


class MemoryClass(StrEnum):
    PERSONAL = "personal"
    DECISION = "decision"
    CONVENTION = "convention"
    LEARNING = "learning"
    EPISODE_SUMMARY = "episode_summary"
    # Workspace scope only, written by the answer-feedback path (``knowledge_answer_feedback``), never by
    # ``memory_remember``; recalled only when a recall names it explicitly.
    ANSWER_FEEDBACK = "answer_feedback"


class MemoryAuthorClass(StrEnum):
    HUMAN_STATED = "human_stated"
    MODEL_INFERRED = "model_inferred"
    VERIFIED = "verified"


class MemoryState(StrEnum):
    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    CONTRADICTED = "contradicted"
    EXPIRED = "expired"
    FORGOTTEN = "forgotten"
    PROMOTED = "promoted"
    # A lesson an agent session proposed for the team: never recalled, shown to nobody's sessions,
    # until someone with the confirmation right confirms it; rejected, it is deleted.
    PROPOSED = "proposed"


MAX_MEMORY_TEXT_CHARS = 2000


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeMemoryItem(Base):
    __tablename__ = "knowledge_memory_items"
    __table_args__ = (
        Index("ix_knowledge_memory_items_visibility", "project_id", "scope", "owner_user_id", "state"),
        Index("ix_knowledge_memory_items_content", "project_id", "content_hash"),
        Index("ix_knowledge_memory_items_supersedes", "supersedes_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    scope = Column(String(20), nullable=False)
    # Personal memory belongs to its person: deleting the user deletes it.
    owner_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    product = Column(String(40), nullable=True)
    item_class = Column(String(30), nullable=False)
    author_class = Column(String(20), nullable=False)
    state = Column(String(20), nullable=False, default=MemoryState.OBSERVED.value)
    # Erased (NULL) once forgotten; the hash goes with it so a forgotten text cannot be confirmed by guessing.
    text = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    # Provenance. The session id is kept as a plain reference: memory outlives the chat that produced it.
    session_id = Column(String(64), nullable=True)
    turn_ref = Column(String(64), nullable=True)
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    supersedes_id = Column(String(36), ForeignKey("knowledge_memory_items.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    # The last state change (confirm, supersede, forget): the tombstone's who and when.
    state_changed_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    state_changed_at = Column(DateTime, nullable=True)


__all__ = [
    "MAX_MEMORY_TEXT_CHARS",
    "KnowledgeMemoryItem",
    "MemoryAuthorClass",
    "MemoryClass",
    "MemoryScope",
    "MemoryState",
]
