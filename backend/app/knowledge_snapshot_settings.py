"""Knowledge repository snapshot settings, a base of :class:`app.config.Settings`.

``OCTRYX_KNOWLEDGE_SNAPSHOT_MAX_FILE_BYTES`` (default 1 MiB) bounds one file of a local repository
snapshot, matching the launcher, which sends files up to 1 MiB. It may be raised up to the general 8 MiB
ingestion limit (``knowledge/ingestion/text_ingest.MAX_TEXT_BYTES``), never beyond it; the upload batch and
request bounds follow it.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

DEFAULT_SNAPSHOT_MAX_FILE_BYTES = 1024 * 1024
MIN_SNAPSHOT_MAX_FILE_BYTES = 64 * 1024
# The general ingestion limit (``text_ingest.MAX_TEXT_BYTES``); not imported, so settings load stays light.
MAX_SNAPSHOT_MAX_FILE_BYTES = 8 * 1024 * 1024


class KnowledgeSnapshotSettings(BaseSettings):
    knowledge_snapshot_max_file_bytes: int = Field(
        default=DEFAULT_SNAPSHOT_MAX_FILE_BYTES,
        ge=MIN_SNAPSHOT_MAX_FILE_BYTES,
        le=MAX_SNAPSHOT_MAX_FILE_BYTES,
        validation_alias=AliasChoices(
            "knowledge_snapshot_max_file_bytes", "OCTRYX_KNOWLEDGE_SNAPSHOT_MAX_FILE_BYTES"
        ),
    )


__all__ = [
    "DEFAULT_SNAPSHOT_MAX_FILE_BYTES",
    "MAX_SNAPSHOT_MAX_FILE_BYTES",
    "MIN_SNAPSHOT_MAX_FILE_BYTES",
    "KnowledgeSnapshotSettings",
]
