"""``user_devices.seat_engines``: the engines whose seat login the device reported at its last handshake."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0010device_seat_engines"
down_revision: str | None = "a0009work_pr_session_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_devices") as batch:
        batch.add_column(sa.Column("seat_engines", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_devices") as batch:
        batch.drop_column("seat_engines")
