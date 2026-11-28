"""``work_pull_requests.session_id`` and ``run_id``: the platform session and run that opened a pull request. Existing
rows stay NULL (no backfill)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0009work_pr_session_run"
down_revision: str | None = "a0008teams_call_proxy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("work_pull_requests") as batch:
        batch.add_column(sa.Column("session_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.create_index(batch.f("ix_work_pull_requests_session_id"), ["session_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("work_pull_requests") as batch:
        batch.drop_index(batch.f("ix_work_pull_requests_session_id"))
        batch.drop_column("run_id")
        batch.drop_column("session_id")
