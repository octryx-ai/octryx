"""The device's own state for remote device sessions: registration, folders, key, pause, limits.

Everything lives in the private state dir (0600 files, covered by the job sandbox's ``denyRead``):

- ``device.json``      ``{device_id, name, os, base_url, folders, max_parallel_jobs, paused, revoked}``;
- ``device-key.pem``   the Ed25519 private key; the channel ``hello`` is signed with it over a server nonce,
                       so a copied token alone cannot impersonate the device;
- ``device-status.json`` what the running service last said (connected, running jobs, needs_login);
- ``logs/device.log``  the service log (rotating).

The folder allowlist is the device's authority: only ``device folders add`` here (with a local confirmation)
widens it; the platform can only narrow it. Every job folder is checked by realpath (symlinks resolved) against
the allowlist again on the device.
"""

from __future__ import annotations

import base64
import os
import platform as host_platform
from pathlib import Path
from typing import Any

from .state import LocalState, read_json, write_private_json

DEVICE_FILE = "device.json"
KEY_FILE = "device-key.pem"
STATUS_FILE = "device-status.json"
LOG_DIR = "logs"
LOG_FILE = "device.log"
LOCK_FILE = "device.lock"

# Six: a team's work items run side by side (on an M4 Pro: with four, a story's fourth
# item waited for the first to merge); a run's ``slot_exempt`` platform turns never take a slot (``device_jobs``).
DEFAULT_PARALLEL_JOBS = 6
MIN_PARALLEL_JOBS = 1
MAX_PARALLEL_JOBS = 8
OS_MACOS = "macos"
OS_LINUX = "linux"
OS_WSL2 = "wsl2"
# macOS privacy (TCC) prompts block background access to these; the service cannot answer a prompt.
MACOS_PROTECTED = ("Desktop", "Documents", "Downloads")


class DeviceStateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def device_path(state: LocalState) -> Path:
    return state.root / DEVICE_FILE


def load_device(state: LocalState) -> dict[str, Any]:
    return read_json(device_path(state))


def save_device(state: LocalState, payload: dict[str, Any]) -> None:
    write_private_json(device_path(state), payload)


def registered(device: dict[str, Any]) -> bool:
    return bool(device.get("device_id")) and not device.get("revoked")


def log_path(state: LocalState) -> Path:
    path = state.root / LOG_DIR
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path / LOG_FILE


def read_status(state: LocalState) -> dict[str, Any]:
    return read_json(state.root / STATUS_FILE)


def write_status(state: LocalState, payload: dict[str, Any]) -> None:
    write_private_json(state.root / STATUS_FILE, payload)


def detect_os(*, system: str | None = None, release: str | None = None, env: dict[str, str] | None = None) -> str:
    """``macos``, ``linux`` or ``wsl2`` (Windows runs octryx-claude inside WSL2)."""
    source = os.environ if env is None else env
    name = (system or host_platform.system()).lower()
    if name == "darwin":
        return OS_MACOS
    if name != "linux":
        raise DeviceStateError("os_not_supported")
    text = (release if release is not None else host_platform.release()).lower()
    if source.get("WSL_DISTRO_NAME") or "microsoft" in text:
        return OS_WSL2
    return OS_LINUX


DEFAULT_CONTEXT_WINDOW = 200_000  # 200k per session, at most 300k
MIN_CONTEXT_WINDOW, MAX_CONTEXT_WINDOW = 100_000, 300_000


def context_window(device: dict) -> int:
    """The context size a Mac turn compacts at (``CLAUDE_CODE_AUTO_COMPACT_WINDOW``)."""
    value = device.get("context_window") if isinstance(device, dict) else None
    if type(value) is int and MIN_CONTEXT_WINDOW <= value <= MAX_CONTEXT_WINDOW:
        return value
    return DEFAULT_CONTEXT_WINDOW


def parallel_jobs(value: object) -> int:
    if type(value) is not int or not MIN_PARALLEL_JOBS <= value <= MAX_PARALLEL_JOBS:
        raise DeviceStateError("parallel_jobs_invalid")
    return value


# --- folders --------------------------------------------------------------------------------------------------


def local_folder(raw: str) -> str:
    """An existing directory as an absolute realpath (``~`` expanded, symlinks resolved)."""
    path = Path(os.path.expanduser(str(raw or ""))).resolve()
    if not str(raw or "").strip() or not path.is_dir():
        raise DeviceStateError("folder_not_found")
    return str(path)


def folder_allowed(folder: str, allowlist: list[str]) -> str:
    """The job folder's realpath when it lies inside an allowlisted folder, else ``""``."""
    try:
        real = Path(os.path.expanduser(folder)).resolve(strict=True)
    except (OSError, RuntimeError):
        return ""
    if not real.is_dir():
        return ""
    for allowed in allowlist:
        try:
            root = Path(allowed).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real == root or root in real.parents:
            return str(real)
    return ""


def protected_folder_warning(folder: str, *, os_name: str, home: Path | None = None) -> str:
    if os_name != OS_MACOS:
        return ""
    base = (home or Path.home()).resolve()
    path = Path(folder)
    for name in MACOS_PROTECTED:
        protected = base / name
        if path == protected or protected in path.parents:
            return (f"warning: {folder} is in ~/{name}; macOS may block background access there. "
                    "Prefer a folder outside Desktop/Documents/Downloads (for example ~/src).")
    return ""


def checkout_note(folder: str) -> str:
    """A note when ``folder`` is not a git checkout: a workflow run works in a clone of its repository (fresh-install
    test: the first run paused with device_turn_repository_not_a_git_repository on an empty folder)."""
    if (Path(folder) / ".git").exists():
        return ""
    return (f"note: {folder} is not a git checkout. A workflow run works in a clone of its repository: "
            f"git clone <repository URL> {folder}")


# --- the device key -------------------------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate_key(state: LocalState) -> str:
    """A new Ed25519 key pair; the private key is written 0600, the public key returned (raw, base64url)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    path = state.ensure().root / KEY_FILE
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    os.chmod(path, 0o600)
    return _b64(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def existing_public_key(state: LocalState) -> str:
    """The public half of the key already on disk (a pending registration's), ``""`` without one."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key

    try:
        private = load_pem_private_key((state.root / KEY_FILE).read_bytes(), password=None)
    except (OSError, ValueError):
        return ""
    return _b64(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def registration_payload(name: str, public_key: str) -> bytes:
    """Signed as ``key_proof``: a retry after a lost answer proves it is the device the platform registered
    (server: ``registration_retry.registration_payload``, the same text)."""
    return f"octryx-device-register:v1:{name.lower()}:{public_key}".encode()


def sign(state: LocalState, data: bytes) -> str:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    try:
        private = load_pem_private_key((state.root / KEY_FILE).read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise DeviceStateError("device_key_missing") from exc
    return _b64(private.sign(data))


def forget_device(state: LocalState) -> None:
    """``device disable``: the key and the device credential go; the user's own login stays."""
    for name in (KEY_FILE, "device-credentials.json", STATUS_FILE):
        try:
            (state.root / name).unlink()
        except FileNotFoundError:
            continue


__all__ = [
    "DEFAULT_PARALLEL_JOBS",
    "DeviceStateError",
    "detect_os",
    "folder_allowed",
    "forget_device",
    "generate_key",
    "load_device",
    "local_folder",
    "log_path",
    "parallel_jobs",
    "protected_folder_warning",
    "checkout_note",
    "read_status",
    "registered",
    "save_device",
    "sign",
    "write_status",
]
