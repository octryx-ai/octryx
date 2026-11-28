"""Durable runtime process records for long-running command execution."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from ..json_text import safe_json_dict, safe_json_list


def uuid_pk() -> str:
    return str(uuid.uuid4())


class RuntimeProcess(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "runtime_processes"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    tool_name = Column(String(120), nullable=False, default="start_runtime_process")
    command_json = Column(Text, default="[]", nullable=False)
    cwd = Column(Text, nullable=False, default="")
    workspace_root = Column(Text, nullable=False, default="")
    status = Column(String(40), nullable=False, default="starting", index=True)
    os_pid = Column(Integer, nullable=True)
    provider = Column(String(40), nullable=False, default="host", index=True)
    timeout_seconds = Column(Integer, nullable=False, default=3600)
    timeout_at = Column(DateTime, nullable=True, index=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True, index=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout_tail = Column(Text, default="", nullable=False)
    stderr_tail = Column(Text, default="", nullable=False)
    output_truncated = Column(Boolean, default=False, nullable=False)
    runtime_metadata_json = Column(Text, default="{}", nullable=False)
    error = Column(Text, nullable=True)

    @property
    def command(self) -> list[str]:
        return [str(item) for item in safe_json_list(self.command_json)]

    @command.setter
    def command(self, value: list[str]) -> None:
        self.command_json = json.dumps([str(item) for item in (value or [])])

    @property
    def runtime_metadata(self) -> dict:
        return safe_json_dict(self.runtime_metadata_json)

    @runtime_metadata.setter
    def runtime_metadata(self, value: dict) -> None:
        self.runtime_metadata_json = json.dumps(value or {})
