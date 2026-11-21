"""One LibreOffice conversion, hardened: no network, minimal environment, locked-down profile, bounded.

Stdlib only and no ``app.*`` import: the render sidecar (``render_server.py``) runs this module in a
container without network, and the API runs it locally only behind a no-network wrapper.

Defences, each independent of the others:

* **No network.** A conversion runs either where the process has no network interface at all (the render
  sidecar, ``network_mode: none``; verified by :func:`only_loopback`) or wrapped by a no-network sandbox
  (Linux ``unshare --net`` in a fresh user namespace, macOS ``sandbox-exec`` denying IP traffic). Where
  neither exists, :func:`isolation_prefix` is ``None`` and there is no render (``office_preview_unavailable``).
* **No API environment.** The child sees ``PATH``, ``HOME``, ``LANG`` and ``TMPDIR`` only (:func:`minimal_env`).
* **Locked-down profile.** Every call gets a fresh LibreOffice profile whose ``registrymodifications.xcu``
  (:func:`profile_xcu`) disables macros at the highest security level, disables active content (OLE, DDE),
  sets link updates to never for Writer and Calc and blocks untrusted referer links.
* **Bounded.** OOXML only, a size cap, two concurrent conversions with fast rejection, CPU/file-size/core
  rlimits, a timeout, and the whole process group killed on timeout *and* cancellation (``soffice`` is a
  launcher; ``soffice.bin`` must not outlive the call).
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import signal
import socket
import subprocess
import tempfile
from pathlib import Path

OFFICE_PREVIEW_UNAVAILABLE = "office_preview_unavailable"
OFFICE_RENDER_FAILED = "office_render_failed"
OFFICE_RENDER_BUSY = "office_render_busy"
OFFICE_RENDER_TOO_LARGE = "office_render_too_large"
OFFICE_RENDER_UNSUPPORTED = "office_render_unsupported_type"

#: OOXML only: the legacy binary import filters (.doc/.xls/.ppt) are not exposed to user files.
RENDERABLE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx"})
RENDER_FORMATS = {"pdf": "application/pdf", "png": "image/png"}
MAX_RENDER_BYTES = 25 * 1024 * 1024
MAX_CONCURRENT_RENDERS = 2
RENDER_TIMEOUT_SEC = 90
CPU_SECONDS_LIMIT = 120
OUTPUT_BYTES_LIMIT = 256 * 1024 * 1024

#: Set in the render sidecar's environment: the container has no network (``network_mode: none``).
SIDECAR_ENV = "OCTRYX_RENDER_SANDBOX"
SIDECAR_NETWORK_NONE = "network_none"

_MAC_APP = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
#: Deny every IP connection, bind and accept; Unix-domain IPC that LibreOffice needs internally stays.
_MAC_NO_IP_PROFILE = (
    "(version 1)(allow default)"
    "(deny network-outbound (remote ip))(deny network-inbound (local ip))(deny network-bind (local ip))"
)


class RenderError(RuntimeError):
    def __init__(self, code: str, fact: str = "") -> None:
        super().__init__(f"{code} {fact}".strip())
        self.code = code


def libreoffice_binary() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return str(_MAC_APP) if _MAC_APP.is_file() else None


# --- network isolation -------------------------------------------------------------------------------------


def only_loopback(interfaces: list[str] | None = None) -> bool:
    """True when the process sees no network interface but loopback (a ``network_mode: none`` container)."""
    names = interfaces if interfaces is not None else [name for _, name in socket.if_nameindex()]
    return all(name == "lo" or name.startswith("lo") and name[2:].isdigit() for name in names)


_UNSHARE_PROBE: bool | None = None


def _unshare_works() -> bool:
    global _UNSHARE_PROBE
    if _UNSHARE_PROBE is None:
        unshare = shutil.which("unshare")
        try:
            _UNSHARE_PROBE = bool(unshare) and subprocess.run(
                [unshare, "--net", "--map-root-user", "true"], capture_output=True, timeout=10, check=False
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _UNSHARE_PROBE = False
    return _UNSHARE_PROBE


def isolation_prefix() -> list[str] | None:
    """The command prefix that takes the network away, ``[]`` where there is none to take, or ``None``."""
    if os.environ.get(SIDECAR_ENV) == SIDECAR_NETWORK_NONE:
        return [] if only_loopback() else None
    system = platform.system()
    if system == "Linux" and _unshare_works():
        return [shutil.which("unshare") or "unshare", "--net", "--map-root-user"]
    if system == "Darwin" and shutil.which("sandbox-exec"):
        return [shutil.which("sandbox-exec") or "sandbox-exec", "-p", _MAC_NO_IP_PROFILE]
    return None


# --- profile and environment -------------------------------------------------------------------------------


def _item(path: str, prop: str, value: str) -> str:
    return (
        f'<item oor:path="{path}"><prop oor:name="{prop}" oor:op="fuse">'
        f"<value>{value}</value></prop></item>"
    )


def profile_xcu() -> str:
    """The per-call ``registrymodifications.xcu``.

    Link update values follow each module's own schema: Writer ``0`` always / ``1`` on request / ``2`` never;
    Calc ``0`` always / ``1`` never / ``2`` on request. Impress has no link-update setting; its linked
    content is covered by ``DisableActiveContent`` and the missing network.
    """
    scripting = "/org.openoffice.Office.Common/Security/Scripting"
    items = [
        _item(scripting, "MacroSecurityLevel", "3"),
        _item(scripting, "DisableMacrosExecution", "true"),
        _item(scripting, "DisableActiveContent", "true"),
        _item(scripting, "DisableOLEAutomation", "true"),
        _item(scripting, "BlockUntrustedRefererLinks", "true"),
        _item("/org.openoffice.Office.Writer/Content/Update", "Link", "2"),
        _item("/org.openoffice.Office.Calc/Content/Update", "Link", "1"),
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n' + "\n".join(items) + "\n</oor:items>\n"
    )


def write_profile(profile_dir: Path) -> Path:
    user_dir = profile_dir / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / "registrymodifications.xcu"
    target.write_text(profile_xcu(), encoding="utf-8")
    return target


def minimal_env(home: Path) -> dict[str, str]:
    """Nothing of the caller's environment but a fixed PATH: no secrets, proxies or credentials."""
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
    }


def _limit_resources() -> None:  # pragma: no cover - runs in the child between fork and exec
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS_LIMIT, CPU_SECONDS_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_BYTES_LIMIT, OUTPUT_BYTES_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def kill_group(process: asyncio.subprocess.Process) -> None:
    """SIGKILL the conversion's whole process group (launcher, oosplash and soffice.bin)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# --- the conversion ----------------------------------------------------------------------------------------

_SEMAPHORE: asyncio.Semaphore | None = None
_SEMAPHORE_LOOP: asyncio.AbstractEventLoop | None = None


def _semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE, _SEMAPHORE_LOOP
    loop = asyncio.get_running_loop()
    if _SEMAPHORE is None or _SEMAPHORE_LOOP is not loop:
        _SEMAPHORE, _SEMAPHORE_LOOP = asyncio.Semaphore(MAX_CONCURRENT_RENDERS), loop
    return _SEMAPHORE


def check_request(suffix: str, size: int, fmt: str) -> None:
    if fmt not in RENDER_FORMATS:
        raise RenderError(OFFICE_RENDER_UNSUPPORTED, "format")
    if suffix.lower() not in RENDERABLE_SUFFIXES:
        raise RenderError(OFFICE_RENDER_UNSUPPORTED, "only .docx, .xlsx and .pptx are rendered")
    if size > MAX_RENDER_BYTES:
        raise RenderError(OFFICE_RENDER_TOO_LARGE, f"limit={MAX_RENDER_BYTES}")


async def convert(
    data: bytes,
    suffix: str,
    fmt: str = "pdf",
    *,
    binary: str | None = None,
    prefix: list[str] | None | str = "auto",
    timeout_sec: float = RENDER_TIMEOUT_SEC,
) -> bytes:
    """Convert one OOXML document; ``prefix`` is the no-network wrapper (``"auto"``: :func:`isolation_prefix`;
    ``None``: there is none, refuse)."""
    check_request(suffix, len(data), fmt)
    wrapper = isolation_prefix() if prefix == "auto" else prefix
    soffice = binary or libreoffice_binary()
    if wrapper is None or soffice is None:
        raise RenderError(OFFICE_PREVIEW_UNAVAILABLE)
    semaphore = _semaphore()
    if semaphore.locked():
        raise RenderError(OFFICE_RENDER_BUSY, f"max={MAX_CONCURRENT_RENDERS}")
    async with semaphore:
        with tempfile.TemporaryDirectory(prefix="octryx-office-render-") as work:
            root = Path(work)
            profile = root / "profile"
            write_profile(profile)
            source = root / f"source{suffix.lower()}"
            source.write_bytes(data)
            out_dir = root / "out"
            command = [
                *wrapper, soffice, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
                f"-env:UserInstallation={profile.as_uri()}", "--convert-to", fmt, "--outdir", str(out_dir), str(source),
            ]
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(root), env=minimal_env(root), start_new_session=True, preexec_fn=_limit_resources,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_sec)
            except TimeoutError as exc:
                raise RenderError(OFFICE_RENDER_FAILED, "timed_out") from exc
            finally:
                # Always: on success the launcher may leave helpers behind, on timeout or cancellation
                # the whole tree must go before the profile directory is removed under it.
                kill_group(process)
                if process.returncode is None:
                    await process.wait()
            produced = out_dir / f"source.{fmt}"
            if process.returncode != 0 or not produced.is_file():
                raise RenderError(OFFICE_RENDER_FAILED, f"exit_code={process.returncode}")
            return produced.read_bytes()


__all__ = [
    "MAX_CONCURRENT_RENDERS",
    "MAX_RENDER_BYTES",
    "OFFICE_PREVIEW_UNAVAILABLE",
    "OFFICE_RENDER_BUSY",
    "OFFICE_RENDER_FAILED",
    "OFFICE_RENDER_TOO_LARGE",
    "OFFICE_RENDER_UNSUPPORTED",
    "RENDERABLE_SUFFIXES",
    "RENDER_FORMATS",
    "SIDECAR_ENV",
    "SIDECAR_NETWORK_NONE",
    "RenderError",
    "check_request",
    "convert",
    "isolation_prefix",
    "kill_group",
    "libreoffice_binary",
    "minimal_env",
    "only_loopback",
    "profile_xcu",
    "write_profile",
]
