"""Source Sync: connectors that keep a Workspace's Knowledge in step with a source system."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

CONNECTOR_KIND_CONFLUENCE = "confluence"
CONNECTOR_KIND_JIRA = "jira"
CONNECTOR_KIND_SERVICENOW = "servicenow"
# A public repository at one commit (repo@commit); credential-free.
CONNECTOR_KIND_GIT_REPOSITORY = "git_repository"
# A cluster's workload inventory (namespaces, deployments, images), read-only (operations graph).
CONNECTOR_KIND_KUBERNETES = "kubernetes"
# A Custom REST definition's list operation, read as an Octryx role through the REST executor.
CONNECTOR_KIND_CUSTOM_REST = "custom_rest"
CONNECTOR_KINDS = frozenset(
    {CONNECTOR_KIND_CONFLUENCE, CONNECTOR_KIND_JIRA, CONNECTOR_KIND_SERVICENOW, CONNECTOR_KIND_GIT_REPOSITORY,
     CONNECTOR_KIND_KUBERNETES, CONNECTOR_KIND_CUSTOM_REST}
)

DEFAULT_SCHEDULE_INTERVAL_MINUTES = 360

CONNECTOR_STATE_ACTIVE = "active"
CONNECTOR_STATE_PAUSED = "paused"

ITEM_STATE_INGESTED = "ingested"
ITEM_STATE_RETIRED = "retired"
ITEM_STATE_WITHHELD = "withheld"
ITEM_STATE_FAILED = "failed"

RUN_STATE_RUNNING = "running"
RUN_STATE_COMPLETED = "completed"
RUN_STATE_BUDGET_EXHAUSTED = "budget_exhausted"
RUN_STATE_FAILED = "failed"
RUN_STATE_NEEDS_CONFIGURATION = "needs_configuration"


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeSourceConnector(WorkspaceBound, Base):
    __tablename__ = "knowledge_source_connectors"
    __table_args__ = (
        UniqueConstraint("project_id", "connector_key", name="uq_knowledge_source_connectors_key"),
        Index("ix_knowledge_source_connectors_workspace", "project_id"),
        Index("ix_knowledge_source_connectors_schedule", "schedule_enabled", "next_scheduled_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connector_key = Column(String(40), nullable=False)
    kind = Column(String(20), nullable=False)
    # The connection this source reads through; null until assigned (no guessing, "assign a connection").
    connection_id = Column(
        String(36), ForeignKey("connector_named_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope = Column(JSON, nullable=False, default=dict)
    products = Column(JSON, nullable=False, default=list)
    version = Column(String(40), nullable=True)
    max_items_per_run = Column(Integer, nullable=False, default=100)
    state = Column(String(20), nullable=False, default=CONNECTOR_STATE_ACTIVE)
    cursor = Column(JSON, nullable=False, default=dict)
    run_lease_until = Column(DateTime, nullable=True)
    last_run_id = Column(String(36), nullable=True)
    # The schedule. Runs act as ``schedule_owner_id``, re-authorized as an author each time.
    schedule_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    schedule_interval_minutes = Column(
        Integer, nullable=False, default=DEFAULT_SCHEDULE_INTERVAL_MINUTES, server_default="360"
    )
    schedule_owner_id = Column(String(36), nullable=True)
    next_scheduled_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeSourceSyncItem(WorkspaceBound, Base):
    __tablename__ = "knowledge_source_sync_items"
    __table_args__ = (
        UniqueConstraint("connector_id", "external_id", name="uq_knowledge_source_sync_items_external"),
        Index("ix_knowledge_source_sync_items_pass", "connector_id", "last_seen_pass"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    connector_id = Column(String(36), ForeignKey("knowledge_source_connectors.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    external_id = Column(String(200), nullable=False)
    source_key = Column(String(200), nullable=False)
    # The ledger source this item currently serves; null once retired or while withheld.
    source_id = Column(String(36), nullable=True)
    content_sha256 = Column(String(64), nullable=True)
    version_marker = Column(String(80), nullable=True)
    # The document role its source ranks with in change answers (``release_notes`` for a Jira release).
    document_role = Column(String(40), nullable=True)
    # The Confluence instance the served content was read from (``sources/sync/provenance.py``); null otherwise.
    source_instance = Column(String(500), nullable=True)
    state = Column(String(20), nullable=False)
    last_outcome = Column(String(40), nullable=False)
    last_seen_pass = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeSourceSyncRun(WorkspaceBound, Base):
    __tablename__ = "knowledge_source_sync_runs"
    __table_args__ = (Index("ix_knowledge_source_sync_runs_connector", "connector_id", "started_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    connector_id = Column(String(36), ForeignKey("knowledge_source_connectors.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    state = Column(String(20), nullable=False, default=RUN_STATE_RUNNING)
    reason = Column(String(40), nullable=True)
    report = Column(JSON, nullable=False, default=dict)
    outcomes = Column(JSON, nullable=False, default=list)
    triggered_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime, nullable=True)


__all__ = [
    "CONNECTOR_KINDS",
    "CONNECTOR_KIND_CUSTOM_REST",
    "CONNECTOR_KIND_CONFLUENCE",
    "CONNECTOR_KIND_GIT_REPOSITORY",
    "CONNECTOR_KIND_JIRA",
    "CONNECTOR_KIND_SERVICENOW",
    "CONNECTOR_STATE_ACTIVE",
    "CONNECTOR_STATE_PAUSED",
    "DEFAULT_SCHEDULE_INTERVAL_MINUTES",
    "ITEM_STATE_FAILED",
    "ITEM_STATE_INGESTED",
    "ITEM_STATE_RETIRED",
    "ITEM_STATE_WITHHELD",
    "RUN_STATE_BUDGET_EXHAUSTED",
    "RUN_STATE_COMPLETED",
    "RUN_STATE_FAILED",
    "RUN_STATE_NEEDS_CONFIGURATION",
    "RUN_STATE_RUNNING",
    "KnowledgeSourceConnector",
    "KnowledgeSourceSyncItem",
    "KnowledgeSourceSyncRun",
]
