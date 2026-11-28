"""``device_jobs.device_id`` nullable: a chat turn waiting for a free server runner has no runner yet (WP-C5)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0015device_job_waiting"
down_revision: str | None = "a0014flow_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("device_jobs") as batch:
        batch.alter_column("device_id", existing_type=sa.String(length=40), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM device_jobs WHERE device_id IS NULL")
    with op.batch_alter_table("device_jobs") as batch:
        batch.alter_column("device_id", existing_type=sa.String(length=40), nullable=False)
