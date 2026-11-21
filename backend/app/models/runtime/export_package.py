import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ExportPackage(Base):
    __tablename__ = "export_packages"
    __table_args__ = (
        Index("ix_export_packages_type_exported_at", "package_type", "exported_at"),
        Index("ix_export_packages_source_entity", "source_entity_type", "source_entity_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    package_type = Column(String(20), nullable=False, index=True)
    entity_name = Column(String(200), nullable=False)
    source_entity_type = Column(String(20), nullable=False)
    source_entity_id = Column(String(36), nullable=False)
    source_project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    content_json = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False, index=True)
    exported_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    exported_at = Column(DateTime, default=utc_now, index=True)


class ImportLog(Base):
    __tablename__ = "import_log"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    package_id = Column(String(36), ForeignKey("export_packages.id"), nullable=True, index=True)
    package_type = Column(String(20), nullable=False, index=True)
    package_checksum = Column(String(64), nullable=False, index=True)
    imported_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    imported_at = Column(DateTime, default=utc_now, index=True)
    status = Column(String(32), nullable=False, default="success", index=True)
    errors = Column(JSON, default=list)
    overwrite_existing = Column(Boolean, default=False)
    target_project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    imported_entity_type = Column(String(20), nullable=True)
    imported_entity_id = Column(String(36), nullable=True)
    imported_entity_name = Column(Text, nullable=True)
