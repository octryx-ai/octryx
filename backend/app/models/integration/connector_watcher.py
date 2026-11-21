import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ConnectorWatcher(Base):
    __tablename__ = "connector_watchers"
    __table_args__ = (
        Index("ix_connector_watchers_connector_active", "connector_name", "is_active"),
        Index("ix_connector_watchers_project_status", "project_id", "status"),
        Index("ix_connector_watchers_mode", "mode"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    connector_name = Column(String(200), nullable=False, index=True)
    connector_instance = Column(String(220), nullable=False, default="default")
    provider_type = Column(String(80), nullable=False, default="generic")
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    mode = Column(String(40), nullable=False, default="webhook")
    event_types_json = Column(JSON, default=list, nullable=False)
    scope_json = Column(JSON, default=dict, nullable=False)
    polling_json = Column(JSON, default=dict, nullable=False)
    webhook_json = Column(JSON, default=dict, nullable=False)
    cursor_json = Column(JSON, default=dict, nullable=False)
    retry_policy_json = Column(JSON, default=dict, nullable=False)
    health_json = Column(JSON, default=dict, nullable=False)
    status = Column(String(80), nullable=False, default="idle")
    last_event_id = Column(String(36), nullable=True)
    last_event_at = Column(DateTime, nullable=True)
    last_cursor = Column(Text, nullable=True)
    dead_letter_count = Column(Integer, nullable=False, default=0)
    secret_ref = Column(String(36), ForeignKey("stored_secrets.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    stored_secret = relationship("StoredSecret")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class ConnectorWatcherEvent(Base):
    __tablename__ = "connector_watcher_events"
    __table_args__ = (
        Index("ix_connector_watcher_events_watcher_received", "watcher_id", "received_at"),
        Index("ix_connector_watcher_events_status", "status"),
        Index("ix_connector_watcher_events_payload_hash", "watcher_id", "payload_hash"),
        Index("ix_connector_watcher_events_external", "watcher_id", "event_type", "external_id"),
        Index("ix_connector_watcher_events_dead_letter", "watcher_id", "status", "attempts"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    watcher_id = Column(String(36), ForeignKey("connector_watchers.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    connector_name = Column(String(200), nullable=False, index=True)
    connector_instance = Column(String(220), nullable=False, default="default")
    provider_type = Column(String(80), nullable=False, default="generic")
    event_type = Column(String(160), nullable=False, default="generic.event")
    external_id = Column(String(260), nullable=True)
    actor = Column(String(260), nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    payload_hash = Column(String(64), nullable=False)
    scope_json = Column(JSON, default=dict, nullable=False)
    raw_payload_ref = Column(Text, nullable=True)
    raw_payload_json = Column(JSON, default=dict, nullable=False)
    normalized_json = Column(JSON, default=dict, nullable=False)
    status = Column(String(80), nullable=False, default="received")
    duplicate_of_event_id = Column(String(36), ForeignKey("connector_watcher_events.id"), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    processing_result_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    watcher = relationship("ConnectorWatcher", foreign_keys=[watcher_id])
    project = relationship("Project")
    duplicate_of = relationship("ConnectorWatcherEvent", remote_side=[id])


class ConnectorWatcherRule(Base):
    __tablename__ = "connector_watcher_rules"
    __table_args__ = (
        Index("ix_connector_watcher_rules_project_active", "project_id", "is_active"),
        Index("ix_connector_watcher_rules_connector_active", "connector_name", "is_active"),
        Index("ix_connector_watcher_rules_priority", "priority"),
        Index("ix_connector_watcher_rules_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    connector_name = Column(String(200), nullable=True, index=True)
    connector_instance = Column(String(220), nullable=True)
    event_types_json = Column(JSON, default=list, nullable=False)
    conditions_json = Column(JSON, default=dict, nullable=False)
    actions_json = Column(JSON, default=list, nullable=False)
    enforcement_json = Column(JSON, default=dict, nullable=False)
    override_roles_json = Column(JSON, default=list, nullable=False)
    rate_limit_json = Column(JSON, default=dict, nullable=False)
    priority = Column(Integer, nullable=False, default=100)
    status = Column(String(80), nullable=False, default="draft")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class ConnectorWatcherRuleDecision(Base):
    __tablename__ = "connector_watcher_rule_decisions"
    __table_args__ = (
        Index("ix_connector_watcher_rule_decisions_event", "event_id", "created_at"),
        Index("ix_connector_watcher_rule_decisions_rule", "rule_id", "created_at"),
        Index("ix_connector_watcher_rule_decisions_action", "decision", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    rule_id = Column(String(36), ForeignKey("connector_watcher_rules.id"), nullable=False, index=True)
    event_id = Column(String(36), ForeignKey("connector_watcher_events.id"), nullable=False, index=True)
    watcher_id = Column(String(36), ForeignKey("connector_watchers.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    decision = Column(String(100), nullable=False, default="audit_only")
    matched = Column(Boolean, nullable=False, default=True)
    actions_json = Column(JSON, default=list, nullable=False)
    reasons_json = Column(JSON, default=list, nullable=False)
    action_results_json = Column(JSON, default=list, nullable=False)
    audit_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    rule = relationship("ConnectorWatcherRule")
    event = relationship("ConnectorWatcherEvent")
    watcher = relationship("ConnectorWatcher")
    project = relationship("Project")
