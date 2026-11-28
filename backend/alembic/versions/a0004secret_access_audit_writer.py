"""``secret_access_audit_log`` records who read a secret for what: ``principal``, ``purpose`` and the secret's own
Workspace (``project_id``, filled from the secret for the rows already there)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0004secret_access_audit"
down_revision: str | None = "a0003worker_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("secret_access_audit_log", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.add_column("secret_access_audit_log", sa.Column("principal", sa.String(length=200), nullable=True))
    op.add_column("secret_access_audit_log", sa.Column("purpose", sa.String(length=100), nullable=True))
    op.create_index(
        op.f("ix_secret_access_audit_log_project_id"), "secret_access_audit_log", ["project_id"], unique=False
    )
    op.execute(
        "UPDATE secret_access_audit_log SET project_id = (SELECT stored_secrets.project_id FROM stored_secrets "
        "WHERE stored_secrets.id = secret_access_audit_log.secret_id) WHERE secret_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_secret_access_audit_log_project_id"), table_name="secret_access_audit_log")
    with op.batch_alter_table("secret_access_audit_log") as batch:
        batch.drop_column("purpose")
        batch.drop_column("principal")
        batch.drop_column("project_id")
