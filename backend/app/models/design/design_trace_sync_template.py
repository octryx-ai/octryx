import json
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now
from ..json_text import safe_json_list


def uuid_pk():
    return str(uuid.uuid4())


class DesignTraceSyncTemplate(Base):
    __tablename__ = "design_trace_sync_templates"

    id = Column(String(64), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    source_kind = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=False)
    mode = Column(String(20), nullable=False, default="auto_link")
    providers_json = Column(Text, default="[]")
    match_rules_json = Column(Text, default="[]")
    limit_per_repository = Column(String(10), nullable=False, default="30")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="design_trace_sync_templates")

    @property
    def providers(self) -> list[str]:
        return [str(item) for item in safe_json_list(self.providers_json)]

    @providers.setter
    def providers(self, value: list[str]):
        self.providers_json = json.dumps(list(value or []))

    @property
    def match_rules(self) -> list[str]:
        return [str(item) for item in safe_json_list(self.match_rules_json)]

    @match_rules.setter
    def match_rules(self, value: list[str]):
        self.match_rules_json = json.dumps(list(value or []))
