"""Drop ``distributed_workers``: the distributed worker runtime that registered its rows is gone."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0003worker_runtime"
down_revision: str | None = "a0002unwired"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("distributed_workers")


# Recreates the table empty; its rows are not restored.
def downgrade() -> None:
    op.create_table(
        "distributed_workers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("backend", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("pod_name", sa.String(length=255), nullable=True),
        sa.Column("queue_name", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["agent_workers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_distributed_workers_heartbeat", "distributed_workers", ["last_heartbeat"], unique=False)
    op.create_index(
        op.f("ix_distributed_workers_last_heartbeat"), "distributed_workers", ["last_heartbeat"], unique=False
    )
    op.create_index(
        "ix_distributed_workers_project_active", "distributed_workers", ["project_id", "is_active"], unique=False
    )
    op.create_index(op.f("ix_distributed_workers_project_id"), "distributed_workers", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_distributed_workers_registered_at"), "distributed_workers", ["registered_at"], unique=False
    )
    op.create_index(op.f("ix_distributed_workers_worker_id"), "distributed_workers", ["worker_id"], unique=False)
