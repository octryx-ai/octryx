"""A user message records who wrote it, so a hand-over does not move the authorship of earlier prompts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0018message_author"
down_revision: str | None = "a0017compression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("author_user_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_messages_author_user_id", "users", ["author_user_id"], ["id"],
                                 ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("fk_messages_author_user_id", type_="foreignkey")
        batch.drop_column("author_user_id")
