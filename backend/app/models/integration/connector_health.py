import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ConnectorHealth(WorkspaceBound, Base):
    __tablename__ = "connector_health"

    connector_name = Column(String(120), primary_key=True)
    project_id = Column(String(36), primary_key=True, default="")
    status = Column(String(24), nullable=False, default="unknown", index=True)
    response_time_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    last_checked = Column(DateTime, nullable=True, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)


class ConnectorHealthLog(WorkspaceBound, Base):
    __tablename__ = "connector_health_log"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    connector_name = Column(String(120), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, default="", index=True)
    status = Column(String(24), nullable=False, index=True)
    response_time_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=utc_now, nullable=False, index=True)
