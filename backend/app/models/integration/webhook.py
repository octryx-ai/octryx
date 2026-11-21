import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # Source: alertmanager, grafana, datadog, pagerduty, sentry, generic (any JSON), jira_change, servicenow_change
    source_type = Column(String(100), default="generic")
    agent_type = Column(String(50), default="diagnosis")
    # The shared secret a caller proves (signature, bearer or X-Webhook-Secret), stored encrypted in StoredSecret.
    secret_ref = Column(String(36), ForeignKey("stored_secrets.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    # The Action an alert starts (workflow + instructions + result destination). No DB-level
    # foreign key; deleting the Action clears it, and a webhook without one is "needs setup".
    task_id = Column(String(36), nullable=True, index=True)
    # Which calls start the Action: critical_warning (default) | all_firing | all
    alert_filter = Column(String(32), nullable=False, default="critical_warning")
    # The same alert (fingerprint) within this window is grouped with the run it started; 0 = never grouped.
    group_window_minutes = Column(Integer, nullable=False, default=30)
    # At most this many started runs per hour; 0 = no limit. Extra alerts are recorded as skipped.
    rate_limit_per_hour = Column(Integer, nullable=False, default=20)
    # A polled source (jira_change / servicenow_change) reads changes through the Workspace's
    # connection every 5 minutes: the JQL or encoded query that selects them, and when it last looked.
    poll_query = Column(Text, nullable=True)
    last_polled_at = Column(DateTime, nullable=True)
    # Replay protection: by default a call must carry a signed X-Webhook-Timestamp (HMAC over "<ts>.<body>",
    # at most 5 minutes off). Only a webhook explicitly set to accept them takes calls without one (tools that
    # cannot sign a timestamp: bearer token or body-only HMAC); duplicates are still refused by the key store.
    accept_untimestamped = Column(Boolean, nullable=False, default=False)

    project = relationship("Project")
    owner = relationship("User")
    events = relationship("WebhookEvent", back_populates="webhook")
    stored_secret = relationship("StoredSecret")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    webhook_id = Column(String(36), ForeignKey("webhooks.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    # received, processing, completed, failed, skipped
    status = Column(String(50), default="received", index=True)
    raw_payload = Column(JSON, nullable=True)
    parsed_message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    received_at = Column(DateTime, default=utc_now, index=True)
    processed_at = Column(DateTime, nullable=True)
    # Outcome log: started | grouped | skipped_resolved | skipped_filtered | skipped_rate_limit |
    # needs_setup | rejected_signature | completed | failed. Nothing an alert causes is dropped silently.
    outcome = Column(String(40), nullable=True, index=True)
    task_run_id = Column(String(36), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=True, index=True)
    alert_title = Column(String(300), nullable=True)
    is_test = Column(Boolean, nullable=False, default=False)

    webhook = relationship("Webhook", back_populates="events")
    session = relationship("Session")


class WebhookDeliveryKey(Base):
    """A call already accepted (delivery id, or a hash of timestamp + body); a second one is a replay."""

    __tablename__ = "webhook_delivery_keys"
    __table_args__ = (UniqueConstraint("webhook_id", "delivery_key", name="uq_webhook_delivery_keys_key"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    webhook_id = Column(String(36), nullable=False, index=True)
    delivery_key = Column(String(128), nullable=False)
    seen_at = Column(DateTime, default=utc_now, nullable=False, index=True)
