"""Drop the tool result compression tables (WP-C4e): the compressor catalog and its log, which only the deleted agent
loop used."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0017compression"
down_revision: str | None = "a0016dead_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_tool_result_compression_log_compressor_id"), table_name="tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compression_log_created_at"), table_name="tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compression_log_request_id"), table_name="tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compression_log_session_id"), table_name="tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compression_log_session_tool"), table_name="tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compression_log_tool_name"), table_name="tool_result_compression_log")
    op.drop_table("tool_result_compression_log")
    op.drop_index(op.f("ix_tool_result_compressors_created_at"), table_name="tool_result_compressors")
    op.drop_index(op.f("ix_tool_result_compressors_tool_active"), table_name="tool_result_compressors")
    op.drop_index(op.f("ix_tool_result_compressors_tool_name"), table_name="tool_result_compressors")
    op.drop_table("tool_result_compressors")


def downgrade() -> None:
    op.create_table(
        "tool_result_compressors",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("tool_name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("strategy", sa.VARCHAR(length=80), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.BOOLEAN(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_result_compressors_tool_name"), "tool_result_compressors", ["tool_name"], unique=1)
    op.create_index(
        op.f("ix_tool_result_compressors_tool_active"),
        "tool_result_compressors",
        ["tool_name", "is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_result_compressors_created_at"), "tool_result_compressors", ["created_at"], unique=False
    )
    op.create_table(
        "tool_result_compression_log",
        sa.Column("id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), nullable=False),
        sa.Column("tool_name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("compressor_id", sa.VARCHAR(length=36), nullable=True),
        sa.Column("strategy", sa.VARCHAR(length=80), nullable=False),
        sa.Column("original_tokens", sa.INTEGER(), nullable=False),
        sa.Column("compressed_tokens", sa.INTEGER(), nullable=False),
        sa.Column("compression_ratio", sa.INTEGER(), nullable=False),
        sa.Column("request_id", sa.VARCHAR(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["compressor_id"],
            ["tool_result_compressors.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_tool_name"), "tool_result_compression_log", ["tool_name"], unique=False
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_session_tool"),
        "tool_result_compression_log",
        ["session_id", "tool_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_session_id"), "tool_result_compression_log", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_request_id"), "tool_result_compression_log", ["request_id"], unique=False
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_created_at"), "tool_result_compression_log", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_tool_result_compression_log_compressor_id"),
        "tool_result_compression_log",
        ["compressor_id"],
        unique=False,
    )
