"""``octryx-claude device enable`` and ``device disable``: register this device to the person, install or remove
its background service, and check the allowlisted folders from this process and from the service."""

from __future__ import annotations

import argparse
import platform as host_platform
import sys
from collections.abc import Callable
from typing import Any

import httpx

from . import __version__, device_folder_access, device_service, device_state
from .device_cli_common import DEVICES_PATH, HTTP_TIMEOUT, _base_url, _fail, _update, _wsl_distro
from .device_cli_status import model_note
from .platform import safe_code
from .profile_choice import seat_logged_in
from .state import CREDENTIAL_SET_DEVICE, LocalState
from .tokens import DEVICE_AUDIENCE, GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

MAX_NAME_CHARS = 80


def _refusal_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"http_{response.status_code}"
    if not isinstance(body, dict):
        return f"http_{response.status_code}"
    return "/".join(code for code in (safe_code(body.get("state")), safe_code(body.get("reason"))) if code) \
        or f"http_{response.status_code}"


def _register(state: LocalState, base_url: str, body: dict[str, Any], http: httpx.Client) -> dict[str, Any] | str:
    try:
        token = get_access_token(state, GATEWAY_AUDIENCE, http=http)
    except TokenUnavailableError as exc:
        return f"needs_configuration: {exc.code} (run: octryx-claude login)"
    try:
        response = http.post(f"{base_url}{DEVICES_PATH}", json=body, headers={"Authorization": f"Bearer {token}"},
                             timeout=HTTP_TIMEOUT)
    except httpx.HTTPError:
        return "platform_unreachable"
    if response.status_code != 201:
        return _refusal_code(response)
    try:
        payload = response.json()
    except ValueError:
        return "invalid_response"
    credential = payload.get("credential") if isinstance(payload, dict) else None
    device = payload.get("device") if isinstance(payload, dict) else None
    if not isinstance(credential, dict) or not isinstance(device, dict) or not credential.get("refresh_token"):
        return "invalid_response"
    return payload


Probe = Callable[[LocalState, list[str]], dict[str, str] | None]


def _local_blocked(folders: list[str], os_name: str) -> str:
    """The refusal for the first folder this process cannot read, else ``""``."""
    for folder in folders:
        if device_folder_access.access_problem(folder):
            return (f"denied: {device_folder_access.REASON_NOT_ACCESSIBLE}: "
                    f"{device_folder_access.access_hint(folder, os_name=os_name)}")
    return ""


def _service_blocked(state: LocalState, folders: list[str], os_name: str, probe: Probe | None, *,
                     started: bool = False) -> tuple[str, bool]:
    """``(refusal, answered)``: the service's own check of ``folders``; asked only when it was just (re)started or
    is known to run (it refreshes its folder verdicts every minute)."""
    if not folders or not (started or device_folder_access.service_alive(state)):
        return "", False
    answer = (probe or device_folder_access.probe_from_service)(state, folders)
    if answer is None:
        return "", False
    python = str(device_state.read_status(state).get("service_python") or "")
    for folder in device_folder_access.blocked(answer):
        return (f"{device_folder_access.REASON_NOT_ACCESSIBLE}: "
                f"{device_folder_access.access_hint(folder, os_name=os_name, python=python)}"), True
    return "", True


def _device_name(raw: str) -> str:
    name = " ".join((raw or host_platform.node() or "").split())[:MAX_NAME_CHARS]
    return name


def _rerun_enable(args: argparse.Namespace, state: LocalState, current: dict[str, Any], *, manager: Any,
                  probe: Probe | None) -> int:
    """``device enable`` on an enabled device: new folders join, the service unit is rewritten and reloaded."""
    os_name = str(current.get("os") or "")
    try:
        folders = [device_state.local_folder(item) for item in args.folder]
    except device_state.DeviceStateError as exc:
        return _fail(f"denied: {exc.code}")
    if refusal := _local_blocked(folders, os_name):
        return _fail(refusal)
    known = list(current.get("folders") or [])
    added = [folder for folder in folders if folder not in known]
    if added:
        _update(state, folders=[*known, *added])
    print(f"This device is already enabled as {current.get('name')} ({current.get('device_id')})."
          + (f" Added {len(added)} folder(s)." if added else ""))
    kind = str(current.get("service_kind") or "")
    if args.no_service or kind not in device_service.KIND_FOR_OS.values():
        return 0
    if int(device_state.read_status(state).get("running_jobs") or 0):
        print("A job is running; the service unit is reloaded when you run `octryx-claude device enable` again "
              "while no job runs.")
    else:
        try:
            service = manager or device_service.manager_for(os_name, distro=_wsl_distro())
            service.install(device_service.service_shim(), device_state.log_path(state))
        except device_service.ServiceError as exc:
            return _fail(f"the background service was not reinstalled: {exc.code}", 1)
        print(f"Background service unit rewritten and reloaded ({kind}).")
    refusal, _answered = _service_blocked(state, added, os_name, probe, started=True)
    return _fail(refusal, 1) if refusal else 0


def _warn_folders(folders: list[str], os_name: str) -> None:
    for folder in folders:
        if warning := device_state.protected_folder_warning(folder, os_name=os_name):
            sys.stderr.write(f"octryx-claude: {warning}\n")
        if note := device_state.checkout_note(folder):
            sys.stderr.write(f"octryx-claude: {note}\n")


def _registration_body(state: LocalState, current: dict[str, Any], *, name: str, base_url: str, os_name: str,
                       folders: list[str], parallel: int, profiles: list[str], kind: str) -> dict[str, Any]:
    """The registration request; the device key is new unless a pending registration of this name is retried."""
    # A pending registration of this name keeps its key: when the answer was lost, the retry proves it is the
    # device the platform registered (a cold run met its own entry as name_taken).
    pending = current.get("pending") if isinstance(current.get("pending"), dict) else {}
    same = pending.get("name") == name and pending.get("base_url") == base_url
    public_key = (same and device_state.existing_public_key(state)) or device_state.generate_key(state)
    device_state.save_device(state, {"pending": {"name": name, "base_url": base_url}})
    return {"name": name, "os": os_name, "public_key": public_key, "folders": folders,
            "profiles_available": profiles, "max_parallel_jobs": parallel, "client_version": __version__,
            "service_kind": kind,
            "key_proof": device_state.sign(state, device_state.registration_payload(name, public_key))}


def _store_registration(state: LocalState, answer: dict[str, Any], *, base_url: str, name: str, os_name: str,
                        folders: list[str], parallel: int, kind: str) -> dict[str, Any]:
    credential, registered = answer["credential"], answer["device"]
    state.with_credential_set(CREDENTIAL_SET_DEVICE).write_credentials({
        "base_url": base_url, "client_id": str(credential.get("client_id") or state.credentials().get("client_id")),
        "refresh_token": str(credential["refresh_token"]), "scopes": list(credential.get("scopes") or []),
        "tokens": {},
    })
    device_state.save_device(state, {
        "device_id": str(registered.get("id")), "name": name, "os": os_name, "base_url": base_url,
        "folders": folders, "max_parallel_jobs": parallel, "paused": False, "service_kind": kind,
    })
    return registered


def _install_after_registration(state: LocalState, *, manager: Any, os_name: str, kind: str, base_url: str,
                                folders: list[str], probe: Probe | None) -> int:
    try:
        service = manager or device_service.manager_for(os_name, distro=_wsl_distro())
        service.install(device_service.service_shim(), device_state.log_path(state))
    except device_service.ServiceError as exc:
        return _fail(f"registered, but the background service was not installed: {exc.code} "
                     "(run `octryx-claude device run` yourself, or retry with `device disable` + `device enable`)", 1)
    print(f"Background service installed ({kind}); it connects outbound to {base_url}.")
    refusal, _answered = _service_blocked(state, folders, os_name, probe, started=True)
    if refusal:
        return _fail(f"{refusal} Jobs in that folder are refused until then; check with `octryx-claude device "
                     "status`.", 1)
    return 0


def run_enable(args: argparse.Namespace, state: LocalState, *, http_factory: Callable[[], httpx.Client] = httpx.Client,
               manager: Any = None, os_name: str | None = None,
               probe: Probe | None = None) -> int:
    base_url = _base_url(state)
    if not base_url:
        return _fail("needs_configuration: not_logged_in (run: octryx-claude login --base-url URL)")
    current = device_state.load_device(state)
    if device_state.registered(current):
        return _rerun_enable(args, state, current, manager=manager, probe=probe)
    try:
        os_name = os_name or device_state.detect_os()
        parallel = device_state.parallel_jobs(args.parallel)
        folders = [device_state.local_folder(item) for item in args.folder]
    except device_state.DeviceStateError as exc:
        return _fail(f"denied: {exc.code}")
    if refusal := _local_blocked(folders, os_name):
        return _fail(refusal)
    name = _device_name(args.name)
    if not name:
        return _fail("denied: device_name_invalid (pass --name)")
    _warn_folders(folders, os_name)
    profiles = ["governed", "seat"] if seat_logged_in(state) else ["governed"]
    kind = device_service.KIND_FOR_OS[os_name] if not args.no_service else "foreground"
    body = _registration_body(state, current, name=name, base_url=base_url, os_name=os_name, folders=folders,
                              parallel=parallel, profiles=profiles, kind=kind)
    with http_factory() as http:
        answer = _register(state, base_url, body, http)
    if isinstance(answer, str):
        if answer == "platform_unreachable":
            return _fail(f"device not enabled: {answer} (the platform may have registered it; run `octryx-claude "
                         "device enable` again: the same device key is reused)")
        device_state.forget_device(state)
        (state.root / device_state.DEVICE_FILE).unlink(missing_ok=True)
        return _fail(f"device not enabled: {answer}")
    registered = _store_registration(state, answer, base_url=base_url, name=name, os_name=os_name, folders=folders,
                                     parallel=parallel, kind=kind)
    print(f"Device {name} ({registered.get('id')}) is registered to you. Folders: {len(folders)}; "
          f"parallel jobs: {parallel}; profiles: {', '.join(profiles)}.")
    if note := model_note(state):
        print(f"Note: {note}.")
    if args.no_service:
        print("No background service installed; run `octryx-claude device run` to connect.")
        return 0
    return _install_after_registration(state, manager=manager, os_name=os_name, kind=kind, base_url=base_url,
                                       folders=folders, probe=probe)


def run_disable(state: LocalState, *, http_factory: Callable[[], httpx.Client] = httpx.Client,
                manager: Any = None) -> int:
    device = device_state.load_device(state)
    if not device.get("device_id"):
        return _fail("this device is not enabled")
    try:
        service = manager or device_service.manager_for(str(device.get("os") or ""), distro=_wsl_distro())
        service.uninstall()
    except device_service.ServiceError as exc:
        sys.stderr.write(f"octryx-claude: warning: the background service could not be removed: {exc.code}\n")
    told = False
    device_creds = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    base_url = str(device.get("base_url") or "")
    with http_factory() as http:
        try:
            token = get_access_token(device_creds, DEVICE_AUDIENCE, http=http)
            response = http.post(f"{base_url}{DEVICES_PATH}/self/disable",
                                 headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
            told = response.status_code == 200
        except (TokenUnavailableError, httpx.HTTPError):
            told = False
    device_state.forget_device(state)
    (state.root / device_state.DEVICE_FILE).unlink(missing_ok=True)
    if not told:
        sys.stderr.write("octryx-claude: warning: the platform could not be told; revoke the device in "
                         "My settings → Devices\n")
    print(f"Device {device.get('name')} disabled; your login stays.")
    return 0
