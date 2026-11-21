"""Schema-state helpers shared by the Alembic model parity test modules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from tests.alembic_model_parity_support import alembic_version, schema_drift

# ``secret_ref`` exists, no plaintext ``secret`` column is left, and ``secret_ref`` references ``stored_secrets``.
WEBHOOK_SECRET_CONTRACT = (True, False, True)


def _schema_state(connection: Connection) -> dict[str, Any]:
    inspector = inspect(connection)
    webhook_columns = {column["name"]: column for column in inspector.get_columns("webhooks")}
    return {
        "drift": schema_drift(connection),
        "version": alembic_version(connection),
        "tables": set(inspector.get_table_names()),
        "webhook_secret_contract": (
            "secret_ref" in webhook_columns,
            "secret" in webhook_columns,
            any(
                foreign_key["constrained_columns"] == ["secret_ref"]
                and foreign_key["referred_table"] == "stored_secrets"
                for foreign_key in inspector.get_foreign_keys("webhooks")
            ),
        ),
    }
