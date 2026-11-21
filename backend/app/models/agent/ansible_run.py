import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class AnsibleJobRun(Base):
    __tablename__ = "ansible_job_runs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    command_type = Column(String(40), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="running", index=True)
    playbook = Column(String(500), nullable=True)
    inventory_path = Column(String(500), nullable=True)
    host_pattern = Column(String(255), nullable=True)
    command = Column(Text, nullable=False)
    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)
    facts_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)
