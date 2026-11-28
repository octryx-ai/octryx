"""Device registry checks: what a device may call itself and report (name, folders, profiles, parallel limit,
key, versions) and the refusal they raise (``devices.registry``)."""

from __future__ import annotations

import base64
import posixpath
import re
from collections.abc import Iterable
from typing import Any

from ...models.security.device import DEFAULT_MAX_PARALLEL_JOBS
from .contract import (
    MAX_FOLDER_CHARS,
    MAX_FOLDERS,
    MAX_NAME_CHARS,
    MAX_PARALLEL_JOBS,
    MIN_PARALLEL_JOBS,
    PROFILES,
    REASON_DEVICE_FOLDERS_INVALID,
    REASON_DEVICE_KEY_INVALID,
    REASON_DEVICE_NAME_INVALID,
    REASON_DEVICE_PARALLEL_INVALID,
    REASON_DEVICE_PROFILES_INVALID,
)

SERVICE_KINDS = ("launchd", "systemd", "wsl-task", "foreground", "runner")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,39}$")


class DeviceRegistryError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_name(value: Any) -> str:
    name = " ".join(str(value or "").split()) if isinstance(value, str) else ""
    if not name or len(name) > MAX_NAME_CHARS or not name.isprintable():
        raise DeviceRegistryError(REASON_DEVICE_NAME_INVALID)
    return name


def normalize_folders(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_FOLDERS:
        raise DeviceRegistryError(REASON_DEVICE_FOLDERS_INVALID)
    folders: list[str] = []
    for item in value:
        if type(item) is not str or not item.startswith("/") or len(item) > MAX_FOLDER_CHARS:
            raise DeviceRegistryError(REASON_DEVICE_FOLDERS_INVALID)
        if "\x00" in item or not item.isprintable() or ".." in item.split("/"):
            raise DeviceRegistryError(REASON_DEVICE_FOLDERS_INVALID)
        folders.append(posixpath.normpath(item))
    return list(dict.fromkeys(folders))


def normalize_profiles(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(item not in PROFILES for item in value):
        raise DeviceRegistryError(REASON_DEVICE_PROFILES_INVALID)
    return [profile for profile in PROFILES if profile in value]


def normalize_parallel_jobs(value: Any) -> int:
    if value is None:
        return DEFAULT_MAX_PARALLEL_JOBS
    if type(value) is not int or not MIN_PARALLEL_JOBS <= value <= MAX_PARALLEL_JOBS:
        raise DeviceRegistryError(REASON_DEVICE_PARALLEL_INVALID)
    return value


def _public_key(value: Any) -> str:
    text = str(value or "") if isinstance(value, str) else ""
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise DeviceRegistryError(REASON_DEVICE_KEY_INVALID) from None
    if len(raw) != 32:
        raise DeviceRegistryError(REASON_DEVICE_KEY_INVALID)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _short_text(value: Any, allowed: Iterable[str] | None = None) -> str | None:
    text = str(value or "").strip() if isinstance(value, str) else ""
    if allowed is not None:
        return text if text in allowed else None
    return text if _VERSION.match(text) else None

