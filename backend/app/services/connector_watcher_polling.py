from __future__ import annotations

from collections.abc import Mapping
from typing import Any

API_INGESTION_TRIGGER_OWNER = "api_ingestion"
POLL_INGEST_ENDPOINT = "/api/v1/connector-watchers/{watcher_id}/poll"
UNSUPPORTED_BACKGROUND_TRIGGER_OWNERS = {
    "background_worker",
    "internal_worker",
    "platform_worker",
    "provider_worker",
    "provider_polling",
}


class UnsupportedPollingTriggerError(ValueError):
    pass


def normalize_connector_watcher_polling_config(value: Any, *, mode: str) -> dict[str, Any]:
    raw = _object_value(value)
    enabled = bool(raw.get("enabled", mode in {"polling", "hybrid"}))
    trigger_owner = _normalize_trigger_owner(raw.get("trigger_owner") or raw.get("trigger"))
    if trigger_owner != API_INGESTION_TRIGGER_OWNER:
        raise UnsupportedPollingTriggerError(_unsupported_trigger_message(trigger_owner))
    return {
        **raw,
        "enabled": enabled,
        "trigger_owner": API_INGESTION_TRIGGER_OWNER,
    }


def describe_connector_watcher_polling_contract(value: Any, *, mode: str) -> dict[str, Any]:
    raw = _object_value(value)
    enabled = bool(raw.get("enabled", mode in {"polling", "hybrid"}))
    trigger_owner = _normalize_trigger_owner(raw.get("trigger_owner") or raw.get("trigger"))
    supported = trigger_owner == API_INGESTION_TRIGGER_OWNER
    return {
        "enabled": enabled,
        "trigger_owner": trigger_owner,
        "supported": supported,
        "background_worker": False,
        "provider_fetcher": False,
        "ingest_endpoint": POLL_INGEST_ENDPOINT,
        "cursor_owner": "poll_ingestion_caller",
        "retry_owner": "connector_watcher_event_retry",
        "notes": _contract_notes(supported=supported, trigger_owner=trigger_owner),
    }


def ensure_api_ingestion_polling_trigger(value: Any) -> None:
    trigger_owner = _normalize_trigger_owner(_object_value(value).get("trigger_owner"))
    if trigger_owner != API_INGESTION_TRIGGER_OWNER:
        raise UnsupportedPollingTriggerError(_unsupported_trigger_message(trigger_owner))


def _normalize_trigger_owner(value: Any) -> str:
    owner = str(value or API_INGESTION_TRIGGER_OWNER).strip().lower()
    if owner in {"", "api", "api_poll", "api_polling"}:
        return API_INGESTION_TRIGGER_OWNER
    return owner


def _unsupported_trigger_message(trigger_owner: str) -> str:
    if trigger_owner in UNSUPPORTED_BACKGROUND_TRIGGER_OWNERS:
        return (
            "Connector watcher polling currently supports only trigger_owner=api_ingestion. "
            "Provider/background polling requires a provider-owned fetch adapter before it can be enabled."
        )
    return (
        f"Unsupported connector watcher polling trigger_owner={trigger_owner}. "
        "Supported trigger_owner is api_ingestion."
    )


def _contract_notes(*, supported: bool, trigger_owner: str) -> str:
    if supported:
        return (
            "Polling events are pushed into Octryx through the authenticated poll ingestion API; "
            "there is no retained-backend background poller for this watcher."
        )
    return _unsupported_trigger_message(trigger_owner)


def _object_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}
