"""``user_devices.engines``: the engines the device reported it can run at its last handshake."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0012device_engines"
down_revision: str | None = "a0011session_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_devices") as batch:
        batch.add_column(sa.Column("engines", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_devices") as batch:
        batch.drop_column("engines")
