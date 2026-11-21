"""Inbound webhook secrets live in the encrypted secret store (VULN-43).

Every create path issues the secret through :func:`issue_webhook_secret` (stored encrypted under
``webhook:<id>`` / ``secret``, referenced by ``webhooks.secret_ref``). The raw value is handed back
once, to the creator, and never listed again.
"""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration.webhook import Webhook
from .secret import get_secret_value, set_secret_value

WEBHOOK_SECRET_FIELD = "secret"


def webhook_secret_tool_name(webhook_id: str) -> str:
    return f"webhook:{webhook_id}"


async def issue_webhook_secret(db: AsyncSession, webhook: Webhook) -> str:
    """Generate, store encrypted and reference a new secret; return the raw value (show it once)."""
    raw_secret = secrets.token_hex(32)
    entry = await set_secret_value(
        db,
        tool_name=webhook_secret_tool_name(webhook.id),
        field_name=WEBHOOK_SECRET_FIELD,
        project_id=webhook.project_id,
        value=raw_secret,
    )
    webhook.secret_ref = entry.id
    return raw_secret


async def resolve_webhook_secret(db: AsyncSession, webhook: Webhook) -> str | None:
    if not webhook.secret_ref:
        return None
    return await get_secret_value(db, secret_id=webhook.secret_ref)


__all__ = ["issue_webhook_secret", "resolve_webhook_secret", "webhook_secret_tool_name"]
