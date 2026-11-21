"""Shared helpers for the test_credential_governance_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.secret import StoredSecret
from app.services.secret.service import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


async def _make_secret(db: AsyncSession) -> StoredSecret:
    """Insert a stored secret with an encrypted value."""
    field_name = f"api_key_{uuid.uuid4().hex[:6]}"
    secret = StoredSecret(
        id=_uid(),
        name=f"test-tool_{field_name}",
        secret_type="test_tool",
        tool_name="test-tool",
        field_name=field_name,
        encrypted_value=encrypt_secret("super-secret-value-123"),
    )
    db.add(secret)
    await db.flush()
    return secret
