"""``session_handovers`` also holds Workspace pool entries: ``to_user_id`` NULL, the run that moves with the session,
the entry's source and what the taker's runtime needs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0011session_pool"
down_revision: str | None = "a0010device_seat_engines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_handovers") as batch:
        batch.alter_column("to_user_id", existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=20), nullable=False, server_default="holder"))
        batch.add_column(sa.Column("needs", sa.JSON(), nullable=True))
        batch.create_index(batch.f("ix_session_handovers_run_id"), ["run_id"], unique=False)
        batch.create_foreign_key("fk_session_handovers_run_id", "workflow_runs", ["run_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("session_handovers") as batch:
        batch.drop_constraint("fk_session_handovers_run_id", type_="foreignkey")
        batch.drop_index(batch.f("ix_session_handovers_run_id"))
        batch.drop_column("needs")
        batch.drop_column("source")
        batch.drop_column("run_id")
        batch.alter_column("to_user_id", existing_type=sa.String(length=36), nullable=False)
