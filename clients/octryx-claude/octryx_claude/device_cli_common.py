"""Shared pieces of the ``octryx-claude device …`` commands: refusals, the local confirmation, the device file."""

from __future__ import annotations

import sys
from typing import Any

from . import configure_cli, device_state
from .state import LocalState

DEVICES_PATH = "/api/v1/devices"
HTTP_TIMEOUT = 15.0


def _fail(message: str, code: int = 2) -> int:
    sys.stderr.write(f"octryx-claude: {message}\n")
    return code


def _ask(prompt: str) -> str:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline()


def _base_url(state: LocalState) -> str:
    config = state.config()
    base_url = configure_cli.normalized_base_url(str(config.get("base_url") or ""))
    if not base_url or state.credentials().get("base_url") != base_url:
        return ""
    return base_url


def _update(state: LocalState, **changes: Any) -> dict[str, Any] | None:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        return None
    device.update(changes)
    device_state.save_device(state, device)
    return device


def _wsl_distro() -> str:
    import os

    return os.environ.get("WSL_DISTRO_NAME", "")
