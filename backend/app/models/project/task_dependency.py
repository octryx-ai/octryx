import uuid

from sqlalchemy import Column, ForeignKey, Index, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound


def uuid_pk() -> str:
    return str(uuid.uuid4())


class TaskDependency(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"task_id": "tasks"}
    __tablename__ = "task_dependencies"
    __table_args__ = (
        Index("ix_task_dependencies_task_dep", "task_id", "depends_on_task_id", unique=True),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    depends_on_task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    condition = Column(String(20), nullable=False, default="success")
