from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from ...db import Base
from ...db.workspace_bound import WorkspaceBound


class ChannelConfig(WorkspaceBound, Base):
    __tablename__ = "channel_configs"

    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(String, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    enabled = Column(Boolean, default=False, nullable=False)
    config = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<ChannelConfig(id={self.id}, plugin_id='{self.plugin_id}', name='{self.name}', enabled={self.enabled})>"
        )
