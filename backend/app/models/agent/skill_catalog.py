"""Central skill catalog: versions, blobs, categories, sources and upstream snapshots.

``skills`` (``models/agent/skill.py``) stays the identity table. Everything that changes what an agent receives,
or who receives it, lives on a :class:`SkillVersion` and goes through the shared governed-revision lifecycle
(``draft -> in_review -> published -> retired``, four-eyes publish, immutable once published).

The canonical artefact of a version is an Agent Skills bundle: ``files`` lists every file (path, sha256, size,
kind) and the bytes live content-addressed in :class:`SkillBlob`. ``frontmatter``/``body`` are the parsed view
of ``SKILL.md``; ``extension`` holds the platform fields (tools per surface, output contract, safety rules, roles,
executor). An MCP server entry (``skills.kind = mcp_server``) carries a ``launch_spec`` instead of a SKILL.md.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from ...db import Base
from ...time_utils import utc_now
from ..runtime.governed_revision import (
    REVISION_STATES,
    in_list,
    install_immutability_guard,
    published_requires_approval_check,
)
from .skill import uuid_pk

DIGEST_LENGTH = 71  # "sha256:" + 64 hex
SHA256_LENGTH = 64

SKILL_KIND_SKILL = "skill"
SKILL_KIND_MCP_SERVER = "mcp_server"
SKILL_KINDS = (SKILL_KIND_SKILL, SKILL_KIND_MCP_SERVER)

TRACKING_PINNED = "pinned"
TRACKING_FOLLOW = "follow"
TRACKING_MODES = (TRACKING_PINNED, TRACKING_FOLLOW)

SOURCE_KIND_GIT = "git"
SOURCE_KIND_UPLOAD = "upload"
SOURCE_KINDS = (SOURCE_KIND_GIT, SOURCE_KIND_UPLOAD)

SOURCE_TRUST_OFFICIAL = "official"
SOURCE_TRUST_COMMUNITY = "community"
SOURCE_TRUST_INTERNAL = "internal"
SOURCE_TRUSTS = (SOURCE_TRUST_OFFICIAL, SOURCE_TRUST_COMMUNITY, SOURCE_TRUST_INTERNAL)

_OPEN_STATES = "state IN ('draft', 'in_review')"
_PUBLISHED_STATE = "state = 'published'"


class SkillCategory(Base):
    """Admin-managed two-level tree; the key is stable so renames keep assignments valid."""

    __tablename__ = "skill_categories"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(80), nullable=False, unique=True)
    label = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    parent_id = Column(String(36), ForeignKey("skill_categories.id"), nullable=True, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class SkillSource(Base):
    """Where imported skills come from: a Git repository (URL, ref, base path) or uploads."""

    __tablename__ = "skill_sources"
    __table_args__ = (
        CheckConstraint(in_list("kind", SOURCE_KINDS), name="ck_skill_sources_kind"),
        CheckConstraint(in_list("trust", SOURCE_TRUSTS), name="ck_skill_sources_trust"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    kind = Column(String(16), nullable=False)
    label = Column(String(200), nullable=False, default="")
    trust = Column(String(16), nullable=False, default=SOURCE_TRUST_COMMUNITY)
    url = Column(String(500), nullable=True)
    ref = Column(String(200), nullable=True)
    base_path = Column(String(500), nullable=False, default="")
    named_connection_id = Column(String(36), nullable=True)
    licence_detected = Column(String(64), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_seen_commit = Column(String(64), nullable=True)
    last_error = Column(String(200), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class SkillBlob(Base):
    """Content-addressed file bytes (UTF-8 text only); shared by every version that carries the same file."""

    __tablename__ = "skill_blobs"

    sha256 = Column(String(SHA256_LENGTH), primary_key=True)
    size = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class SkillUpstreamSnapshot(Base):
    """The upstream files of one skill path at one commit: the base of the 3-way merge, never re-fetched."""

    __tablename__ = "skill_upstream_snapshots"
    __table_args__ = (UniqueConstraint("source_id", "path", "commit", name="uq_skill_upstream_snapshots"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    source_id = Column(String(36), ForeignKey("skill_sources.id"), nullable=False, index=True)
    path = Column(String(500), nullable=False)
    commit = Column(String(64), nullable=False)
    files = Column(JSON, nullable=False, default=list)
    bundle_digest = Column(String(DIGEST_LENGTH), nullable=False)
    fetched_at = Column(DateTime, nullable=False, default=utc_now)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        CheckConstraint(in_list("state", REVISION_STATES), name="ck_skill_versions_state"),
        CheckConstraint("version >= 1", name="ck_skill_versions_version"),
        CheckConstraint(published_requires_approval_check(), name="ck_skill_versions_published"),
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
        # At most one open (draft or in review) and at most one published version per skill.
        Index("uq_skill_versions_open", "skill_id", unique=True,
              sqlite_where=text(_OPEN_STATES), postgresql_where=text(_OPEN_STATES)),
        Index("uq_skill_versions_published", "skill_id", unique=True,
              sqlite_where=text(_PUBLISHED_STATE), postgresql_where=text(_PUBLISHED_STATE)),
        Index("ix_skill_versions_state", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    digest = Column(String(DIGEST_LENGTH), nullable=False)
    frontmatter = Column(JSON, nullable=False, default=dict)
    body = Column(Text, nullable=False, default="")
    extension = Column(JSON, nullable=False, default=dict)
    launch_spec = Column(JSON, nullable=True)
    category_id = Column(String(36), ForeignKey("skill_categories.id"), nullable=True)
    available_platform_chat = Column(Boolean, nullable=False, default=True)
    available_octryx_claude = Column(Boolean, nullable=False, default=True)
    licence_spdx = Column(String(64), nullable=True)
    files = Column(JSON, nullable=False, default=list)
    bundle_digest = Column(String(DIGEST_LENGTH), nullable=False)
    scripts_allowed = Column(Boolean, nullable=False, default=False)
    scripts_allowed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    scripts_reason = Column(Text, nullable=True)
    acknowledged_findings = Column(JSON, nullable=False, default=list)
    upstream_source_id = Column(String(36), ForeignKey("skill_sources.id"), nullable=True)
    upstream_path = Column(String(500), nullable=True)
    upstream_commit = Column(String(64), nullable=True)
    upstream_bundle_digest = Column(String(DIGEST_LENGTH), nullable=True)
    base_version = Column(Integer, nullable=True)
    merge_report = Column(JSON, nullable=True)
    security_report = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)
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


install_immutability_guard(SkillVersion)


__all__ = [
    "DIGEST_LENGTH",
    "SKILL_KINDS",
    "SKILL_KIND_MCP_SERVER",
    "SKILL_KIND_SKILL",
    "SOURCE_KINDS",
    "SOURCE_KIND_GIT",
    "SOURCE_KIND_UPLOAD",
    "SOURCE_TRUSTS",
    "SOURCE_TRUST_COMMUNITY",
    "SOURCE_TRUST_INTERNAL",
    "SOURCE_TRUST_OFFICIAL",
    "TRACKING_FOLLOW",
    "TRACKING_MODES",
    "TRACKING_PINNED",
    "SkillBlob",
    "SkillCategory",
    "SkillSource",
    "SkillUpstreamSnapshot",
    "SkillVersion",
]
