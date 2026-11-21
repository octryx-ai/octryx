"""Connector watchers: webhook and polling event intake, deduplication, retries and health.

The implementation lives in the modules of this package; this module keeps the names its callers import.
"""

from __future__ import annotations

from .common import DEFAULT_RETRY_POLICY, EVENT_STATUSES, MAX_EVENTS, WATCHER_MODES
from .ingest import (
    ingest_connector_poll_events,
    ingest_connector_webhook_event,
    list_connector_watcher_events,
    retry_connector_watcher_event,
)
from .serialize import serialize_connector_watcher, serialize_watcher_event
from .watchers import create_connector_watcher, list_connector_watchers, update_connector_watcher

__all__ = [
    "DEFAULT_RETRY_POLICY",
    "EVENT_STATUSES",
    "MAX_EVENTS",
    "WATCHER_MODES",
    "create_connector_watcher",
    "ingest_connector_poll_events",
    "ingest_connector_webhook_event",
    "list_connector_watcher_events",
    "list_connector_watchers",
    "retry_connector_watcher_event",
    "serialize_connector_watcher",
    "serialize_watcher_event",
    "update_connector_watcher",
]
