"""Drop the Teams call-proxy redirect target: ``call_agent_configs.calling_webhook_url`` and the Teams channel key."""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0008teams_call_proxy"
down_revision: str | None = "a0007audit_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_KEY = "calling_webhook_url"


def _drop_channel_key() -> None:
    connection = op.get_bind()
    channels = sa.table("channel_configs", sa.column("id", sa.Integer), sa.column("plugin_id", sa.String),
                        sa.column("config", sa.Text))
    rows = connection.execute(sa.select(channels.c.id, channels.c.config).where(channels.c.plugin_id == "msteams"))
    for channel_id, raw in rows.all():
        try:
            config = json.loads(raw or "{}")
        except ValueError:
            continue
        if isinstance(config, dict) and _CHANNEL_KEY in config:
            del config[_CHANNEL_KEY]
            connection.execute(channels.update().where(channels.c.id == channel_id).values(config=json.dumps(config)))


def upgrade() -> None:
    with op.batch_alter_table("call_agent_configs") as batch:
        batch.drop_column("calling_webhook_url")
    _drop_channel_key()


# Restores the column empty; the removed URLs are not restored.
def downgrade() -> None:
    with op.batch_alter_table("call_agent_configs") as batch:
        batch.add_column(sa.Column("calling_webhook_url", sa.String(length=500), nullable=True))
