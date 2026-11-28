"""How a device is shown to its owner or to an admin (``devices.registry``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...models import UserDevice
from ...models.security.device import DEFAULT_MAX_PARALLEL_JOBS


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_device(device: UserDevice, *, owner_view: bool, live: Mapping[str, Any] | None = None,
                     needs_login: bool = False, login_expires_at: Any = None) -> dict[str, Any]:
    live = live or {}
    payload: dict[str, Any] = {
        "id": device.id,
        "name": device.name,
        "os": device.os,
        "status": device.status,
        "paused": bool(device.paused),
        "connected": bool(live.get("connected")),
        "running_jobs": int(live.get("running_jobs") or 0),
        "max_parallel_jobs": int(device.max_parallel_jobs or DEFAULT_MAX_PARALLEL_JOBS),
        "profiles": list(device.profiles or []),
        "client_version": device.client_version,
        "service_kind": device.service_kind,
        "folder_count": len(device.folders or []),
        "created_at": _iso(device.created_at),
        "last_seen_at": _iso(device.last_seen_at),
        "revoked_at": _iso(device.revoked_at),
        # When the platform's device login validity ends (``login_validity``); then ``device enable`` again.
        "login_expires_at": _iso(login_expires_at),
    }
    # The launcher's pinned tools the connected device has ({id: version | None}); the review bot chooses by them.
    payload["tools"] = dict(live.get("tools") or {})
    if owner_view:
        payload["folders"] = list(device.folders or [])
        payload["seat_login"] = bool(live.get("seat_login"))
        # The Codex seat (the person's own ChatGPT login) signed in on this device; yes/no only.
        payload["codex_seat_login"] = bool(live.get("codex_seat_login"))
        payload["needs_login"] = needs_login and not live.get("connected")
    else:
        payload["owner_user_id"] = device.owner_user_id
    return payload

