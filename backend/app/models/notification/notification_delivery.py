from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        Index("ix_notification_templates_event_channel", "event_type", "channel_type"),
        Index("ix_notification_templates_project_active", "project_id", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(160), nullable=False)
    event_type = Column(String(100), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    subject_template = Column(Text, nullable=True)
    body_template = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        Index("ix_notification_subscriptions_event", "event_type"),
        Index("ix_notification_subscriptions_user_active", "user_id", "is_active"),
        Index("ix_notification_subscriptions_project_active", "project_id", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False, index=True)
    channel_config_id = Column(Integer, ForeignKey("channel_configs.id"), nullable=True, index=True)
    target = Column(String(500), nullable=False)
    template_id = Column(String(36), ForeignKey("notification_templates.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    user = relationship("User", foreign_keys=[user_id])
    project = relationship("Project")
    channel_config = relationship("ChannelConfig")
    template = relationship("NotificationTemplate")
    creator = relationship("User", foreign_keys=[created_by])


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        Index("ix_notification_log_status_next_retry", "status", "next_retry_at"),
        Index("ix_notification_log_subscription_created", "subscription_id", "created_at"),
        Index("ix_notification_log_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    notification_id = Column(String(36), ForeignKey("notifications.id"), nullable=True, index=True)
    subscription_id = Column(String(36), ForeignKey("notification_subscriptions.id"), nullable=True, index=True)
    template_id = Column(String(36), ForeignKey("notification_templates.id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False, index=True)
    channel_config_id = Column(Integer, ForeignKey("channel_configs.id"), nullable=True, index=True)
    target = Column(String(500), nullable=False)
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pending", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    notification = relationship("Notification")
    subscription = relationship("NotificationSubscription")
    template = relationship("NotificationTemplate")
    user = relationship("User")
    project = relationship("Project")
    channel_config = relationship("ChannelConfig")
