"""Knowledge retention settings, a base of :class:`app.config.Settings`: how often the background workers reconcile
every Workspace with a retention policy (``OCTRYX_KNOWLEDGE_RETENTION_RECONCILE_INTERVAL_HOURS``, default 24)."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

DEFAULT_RECONCILE_INTERVAL_HOURS = 24
MAX_RECONCILE_INTERVAL_HOURS = 24 * 30


class KnowledgeRetentionSettings(BaseSettings):
    knowledge_retention_reconcile_interval_hours: int = Field(
        default=DEFAULT_RECONCILE_INTERVAL_HOURS,
        ge=1,
        le=MAX_RECONCILE_INTERVAL_HOURS,
        validation_alias=AliasChoices(
            "knowledge_retention_reconcile_interval_hours", "OCTRYX_KNOWLEDGE_RETENTION_RECONCILE_INTERVAL_HOURS"
        ),
    )


__all__ = ["DEFAULT_RECONCILE_INTERVAL_HOURS", "MAX_RECONCILE_INTERVAL_HOURS", "KnowledgeRetentionSettings"]
