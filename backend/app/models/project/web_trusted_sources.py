"""The trusted-source registry of the governed web search (search control plane).

One row is one source pattern (a host, optionally with a path prefix, such as ``docs.spring.io`` or
``github.com/spring-projects/spring-boot/wiki``) in one scope: the whole platform, or one
Workspace. Its state decides what research and search may use:

- ``trusted``: research searches and follows links there, and its documents may be ingested;
- ``proposed``: an agent found it (a verified entry point) and asks an admin to decide;
- ``blocked``: never searched, never fetched, dropped from every search result.

``scope_key`` is ``platform`` or the Workspace id, so one unique index covers both scopes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now

SCOPE_PLATFORM = "platform"

SOURCE_STATE_PROPOSED = "proposed"
SOURCE_STATE_TRUSTED = "trusted"
SOURCE_STATE_BLOCKED = "blocked"
SOURCE_STATES = (SOURCE_STATE_PROPOSED, SOURCE_STATE_TRUSTED, SOURCE_STATE_BLOCKED)

ORIGIN_ADMIN = "admin"
ORIGIN_AGENT = "agent"


def _uuid() -> str:
    return str(uuid.uuid4())


class WebTrustedSource(Base):
    __tablename__ = "web_trusted_sources"
    __table_args__ = (
        UniqueConstraint("scope_key", "pattern", name="uq_web_trusted_sources_scope_pattern"),
        Index("ix_web_trusted_sources_scope", "scope_key"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    scope_key = Column(String(36), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    pattern = Column(String(300), nullable=False)
    products = Column(JSON, nullable=False, default=list)
    state = Column(String(20), nullable=False)
    origin = Column(String(20), nullable=False)
    reason = Column(Text, nullable=False, default="")
    evidence_url = Column(String(2048), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    decided_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = [
    "ORIGIN_ADMIN",
    "ORIGIN_AGENT",
    "SCOPE_PLATFORM",
    "SOURCE_STATES",
    "SOURCE_STATE_BLOCKED",
    "SOURCE_STATE_PROPOSED",
    "SOURCE_STATE_TRUSTED",
    "WebTrustedSource",
]
