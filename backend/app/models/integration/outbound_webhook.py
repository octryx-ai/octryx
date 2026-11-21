import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now
from ..json_text import dump_string_list, safe_string_list


def uuid_pk() -> str:
    return str(uuid.uuid4())


class OutboundWebhook(Base):
    __tablename__ = "outbound_webhooks"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    url = Column(Text, nullable=False)
    secret_hash = Column(String(128), nullable=False)
    encrypted_secret = Column(Text, nullable=False)
    event_types_json = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    last_delivery_status = Column(String(50), nullable=True)
    last_delivery_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")
    creator = relationship("User")

    @property
    def event_types(self) -> list[str]:
        return safe_string_list(self.event_types_json)

    @event_types.setter
    def event_types(self, value: list[str] | tuple[str, ...]) -> None:
        self.event_types_json = dump_string_list(list(value or []))


class OutboundWebhookDelivery(Base):
    __tablename__ = "outbound_webhook_deliveries"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    webhook_id = Column(String(36), ForeignKey("outbound_webhooks.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(Text, default="{}")
    request_id = Column(String(100), nullable=True)
    status = Column(String(50), default="pending")
    retry_count = Column(Integer, default=0)
    http_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    webhook = relationship("OutboundWebhook")
    project = relationship("Project")
