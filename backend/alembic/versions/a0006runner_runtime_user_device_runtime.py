"""``user_devices.runtime``: the container runtime a server runner reported at enrollment (gVisor or the default)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0006runner_runtime"
down_revision: str | None = "a0005channel_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_devices", sa.Column("runtime", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("user_devices", "runtime")
