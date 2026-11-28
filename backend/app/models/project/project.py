import uuid

from sqlalchemy import (
    JSON,
    Boolean,
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
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Project(WorkspaceBound, Base):
    __workspace_column__ = "id"
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    source_type = Column(String(30), default="manual", nullable=False, index=True)
    template_key = Column(String(160), nullable=True, index=True)
    template_version = Column(String(80), nullable=True)
    template_metadata = Column(JSON, default=dict)
    is_system = Column(Boolean, default=False, nullable=False, index=True)
    access_mode = Column(String(20), default="team", nullable=False, index=True)
    # A person's private Workspace: ``access_mode == "private"`` and its one owner. Nobody else,
    # platform admins included, gets a role in it (``services/project/private_workspace``).
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    users = relationship(
        "User",
        secondary="user_projects",
        primaryjoin="Project.id == UserProject.project_id",
        secondaryjoin="User.id == UserProject.user_id",
        back_populates="projects",
    )
    sessions = relationship("Session", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project")
    design_artifacts = relationship("DesignArtifact", back_populates="project", cascade="all, delete-orphan")
    design_trace_sync_templates = relationship(
        "DesignTraceSyncTemplate", back_populates="project", cascade="all, delete-orphan"
    )
    workspace_capability_bindings = relationship(
        "WorkspaceCapabilityBinding", back_populates="workspace", cascade="all, delete-orphan"
    )
    workspace_policy = relationship(
        "WorkspacePolicy", back_populates="workspace", cascade="all, delete-orphan", uselist=False
    )
    research_policy_assignment = relationship(
        "WorkspaceResearchPolicyAssignment",
        back_populates="workspace",
        cascade="all, delete-orphan",
        uselist=False,
    )


class KnowledgeChunk(WorkspaceBound, Base):
    """A text chunk of a source document — the naive vector-RAG substrate (tier 1)."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("project_id", "source_ref", "chunk_index", name="uq_knowledge_chunks_source_index"),
        Index("ix_knowledge_chunks_project", "project_id"),
        Index("ix_knowledge_chunks_source", "project_id", "source_ref"),
        Index("ix_knowledge_chunks_embedding_updated_at", "embedding_updated_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    # Nullable: NULL means instance-global knowledge (e.g. published pack
    # items) visible to every project — same scope rule as graph nodes.
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    source_ref = Column(String(300), nullable=False, index=True)
    source_kind = Column(String(60), default="document", nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    tags = Column(JSON, default=list)
    embedding = Column(JSON, default=list)
    embedding_provider = Column(String(80), nullable=True)
    embedding_model = Column(String(50), nullable=True)
    embedding_version = Column(String(80), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")
