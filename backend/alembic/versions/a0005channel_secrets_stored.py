"""Channel credentials move from the plain ``channel_configs.config`` JSON into ``stored_secrets`` (owned by the
channel, in its Workspace); the config keeps ``<field>_secret_ref``."""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "a0005channel_secrets"
down_revision: str | None = "a0004secret_access_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DECLARED_SECRETS = {
    "msteams": ("app_password",),
    "slack": ("bot_token", "signing_secret"),
    "email": ("smtp_password", "imap_password"),
    "matrix": ("password", "access_token"),
    "telegram": ("bot_token",),
}
_REF_SUFFIX = "_secret_ref"

_channels = sa.table("channel_configs", sa.column("id", sa.Integer()), sa.column("plugin_id", sa.String()),
                     sa.column("project_id", sa.String()), sa.column("config", sa.Text()))
_secrets = sa.table(
    "stored_secrets", sa.column("id", sa.String()), sa.column("name", sa.String()),
    sa.column("secret_type", sa.String()), sa.column("project_id", sa.String()), sa.column("tool_name", sa.String()),
    sa.column("field_name", sa.String()), sa.column("encrypted_value", sa.Text()),
    sa.column("last_rotated_at", sa.DateTime()), sa.column("created_at", sa.DateTime()),
    sa.column("updated_at", sa.DateTime()))


def _secret_keys(plugin_id: str, config: dict) -> list[str]:
    from app.services.redaction_policy import is_sensitive_key

    declared = set(DECLARED_SECRETS.get(plugin_id, ()))
    return sorted(key for key in config
                  if not key.endswith(_REF_SUFFIX) and (key in declared or is_sensitive_key(key)))


def _config(raw: object) -> dict:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def upgrade() -> None:
    # The app's own encryption, so the service decrypts what this writes (instance ``encryption_key``).
    from app.services.secret.crypto import encrypt_secret

    connection = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    for channel_id, plugin_id, project_id, raw in connection.execute(
            sa.select(_channels.c.id, _channels.c.plugin_id, _channels.c.project_id, _channels.c.config)).all():
        config = _config(raw)
        keys = _secret_keys(str(plugin_id), config)
        if not keys:
            continue
        tool_name = f"channel:{channel_id}"
        for key in keys:
            value = config.pop(key)
            if value is None or str(value).strip() == "":
                continue
            secret_id = str(uuid.uuid4())
            connection.execute(_secrets.insert().values(
                id=secret_id, name=f"{tool_name}_{key}", secret_type=tool_name, project_id=project_id,
                tool_name=tool_name, field_name=key, encrypted_value=encrypt_secret(str(value)),
                last_rotated_at=now, created_at=now, updated_at=now))
            config[f"{key}{_REF_SUFFIX}"] = secret_id
        connection.execute(_channels.update().where(_channels.c.id == channel_id).values(config=json.dumps(config)))


def downgrade() -> None:
    from app.services.secret.crypto import decrypt_secret

    connection = op.get_bind()
    for channel_id, raw in connection.execute(sa.select(_channels.c.id, _channels.c.config)).all():
        config = _config(raw)
        refs = {key[: -len(_REF_SUFFIX)]: value for key, value in config.items() if key.endswith(_REF_SUFFIX)}
        if not refs:
            continue
        for field, secret_id in refs.items():
            config.pop(f"{field}{_REF_SUFFIX}")
            encrypted = connection.execute(sa.select(_secrets.c.encrypted_value).where(
                _secrets.c.id == secret_id)).scalar_one_or_none()
            if encrypted:
                config[field] = decrypt_secret(encrypted)
        connection.execute(_channels.update().where(_channels.c.id == channel_id).values(config=json.dumps(config)))
        released = list(refs.values())
        connection.execute(sa.text("UPDATE secret_access_audit_log SET secret_id = NULL WHERE secret_id IN :ids")
                           .bindparams(sa.bindparam("ids", expanding=True)), {"ids": released})
        connection.execute(sa.delete(_secrets).where(_secrets.c.id.in_(released)))
