import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class DataExportJob(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_scope__ = ("scope_type", ("project",), "scope_id")
    __tablename__ = "data_export_jobs"
    __table_args__ = (
        Index("ix_data_export_jobs_type_created", "export_type", "created_at"),
        Index("ix_data_export_jobs_scope", "scope_type", "scope_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    export_type = Column(String(50), nullable=False, index=True)
    scope_type = Column(String(20), nullable=False, index=True)
    scope_id = Column(String(36), nullable=True, index=True)
    format = Column(String(10), nullable=False, default="json")
    include_sensitive = Column(Boolean, default=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    file_url = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    summary_json = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)


class DataImportJob(WorkspaceBound, Base):
    __workspace_column__ = "target_project_id"
    __tablename__ = "data_import_jobs"
    __table_args__ = (Index("ix_data_import_jobs_type_created", "import_type", "created_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    import_type = Column(String(50), nullable=False, index=True)
    source_format = Column(String(10), nullable=False, default="json")
    rows_total = Column(Integer, default=0)
    rows_success = Column(Integer, default=0)
    rows_failed = Column(Integer, default=0)
    errors = Column(JSON, default=list)
    status = Column(String(20), nullable=False, default="pending", index=True)
    target_project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    summary_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)
