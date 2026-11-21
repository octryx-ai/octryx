import uuid

from sqlalchemy import Column, ForeignKey, Index, String

from ...db import Base


def uuid_pk() -> str:
    return str(uuid.uuid4())


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        Index("ix_task_dependencies_task_dep", "task_id", "depends_on_task_id", unique=True),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    depends_on_task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    condition = Column(String(20), nullable=False, default="success")
