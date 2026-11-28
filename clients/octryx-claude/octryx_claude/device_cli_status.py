"""``octryx-claude device status`` and ``device tools``: what the device, its service and its tools look like."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx

from . import device_folder_access, device_service, device_state
from .device_cli_common import _wsl_distro
from .state import CREDENTIAL_SET_DEVICE, LocalState


def _folder_line(folder: str, live: dict[str, Any], os_name: str) -> str:
    verdicts = live.get("folder_access") if isinstance(live.get("folder_access"), dict) else {}
    if folder not in verdicts:
        return f"  {folder}"
    if verdicts[folder] == device_folder_access.REASON_NOT_ACCESSIBLE:
        hint = device_folder_access.access_hint(folder, os_name=os_name, python=str(live.get("service_python") or ""))
        return f"  {folder} · {device_folder_access.REASON_NOT_ACCESSIBLE}: {hint}"
    return f"  {folder} · accessible to the service"


# The connected service rewrites its status at least every minute (``device_channel`` heartbeat).
STATUS_STALE_SECONDS = 3 * 60


def _connection_line(device: dict[str, Any], live: dict[str, Any], *, service_running: bool | None,
                     now: float | None = None) -> str:
    if device.get("revoked") or live.get("revoked"):
        return " · revoked (the service asks the platform again periodically; or run: device enable)"
    if live.get("connected"):
        updated = live.get("updated_at")
        age = (time.time() if now is None else now) - float(updated) if isinstance(updated, int | float) else 0.0
        if service_running is False or age > STATUS_STALE_SECONDS:
            return " · unknown (status stale: the service is not running or not reporting)"
        return f" · connected · {int(live.get('running_jobs') or 0)} running"
    line = " · offline"
    if live.get("idle_reason"):
        line += f" ({live['idle_reason']})"
    elif live.get("last_error"):
        line += f" (last error: {live['last_error']}, attempt {int(live.get('attempt') or 0)})"
    return line


def run_status(state: LocalState, *, manager: Any = None) -> int:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        print("device: not enabled (run: octryx-claude device enable --name NAME --folder PATH)")
        return 0
    live = device_state.read_status(state)
    service_running: bool | None = None
    try:
        service = manager or device_service.manager_for(str(device.get("os") or ""), distro=_wsl_distro())
        status = service.status()
        shown = "running" if status.running else "installed" if status.installed else "not installed"
        service_line = f"{status.kind} · {shown}"
        service_running = bool(status.running) if status.installed else None
    except device_service.ServiceError as exc:
        service_line = f"unknown ({exc.code})"
    credential = state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()
    lines = [
        f"device:     {device.get('name')} ({device.get('device_id')}) · {device.get('os')}",
        f"platform:   {device.get('base_url')}",
        f"service:    {service_line}",
        f"credential: {'present' if credential.get('refresh_token') else 'missing (run: device enable)'}"
        + (" · needs_login" if live.get("needs_login") else ""),
        f"state:      {'paused' if device.get('paused') else 'accepting jobs'}"
        + _connection_line(device, live, service_running=service_running),
        f"parallel:   {device.get('max_parallel_jobs', device_state.DEFAULT_PARALLEL_JOBS)}",
        "folders:",
        *([_folder_line(folder, live, str(device.get("os") or "")) for folder in device.get("folders") or []]
          or ["  (none)"]),
        "tools:      " + _tools_line(state),
    ]
    if note := model_note(state):
        lines.append(f"models:     {note}")
    print("\n".join(lines))
    return 0


POLICY_TIMEOUT = 10.0


def model_note(state: LocalState) -> str:
    import uuid  # noqa: PLC0415

    from . import status_block  # noqa: PLC0415
    from .platform import SessionContext, call_control_plane, valid_header_value  # noqa: PLC0415

    config = state.config()
    base_url, workspace_id = str(config.get("base_url") or ""), str(config.get("workspace_id") or "")
    credentials = state.credentials()
    if not base_url or not valid_header_value(workspace_id) or not credentials.get("refresh_token") \
            or credentials.get("base_url") != base_url:
        return ""
    try:
        with httpx.Client() as http:
            result = call_control_plane(state, SessionContext(base_url, str(uuid.uuid4()), workspace_id), "GET",
                                        "/client-policy", http=http, timeout=POLICY_TIMEOUT)
    except (httpx.HTTPError, OSError, ValueError):
        return ""
    if not status_block.policy_ok(result):
        return ""
    return status_block.model_note(result.body, status_block.seat_state_for(state, result))


def _tools_line(state: LocalState) -> str:
    from . import tools  # noqa: PLC0415

    return ", ".join(f"{name} {value}" for name, value in tools.tool_states(state.root).items())


def run_tools(args: argparse.Namespace, state: LocalState) -> int:
    from . import tools  # noqa: PLC0415

    problems = tools.ensure(state.root) if args.ensure else []
    for name, version in tools.inventory(state.root).items():
        print(f"{name:12} {version or 'missing'}")
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    return 1 if problems else 0
