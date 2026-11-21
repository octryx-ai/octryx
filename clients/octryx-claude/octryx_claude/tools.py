"""The tools the launcher brings (``tools_data.TOOLS``): what this device has, getting the missing ones, and the
folders a device run puts first on ``PATH`` (everything the platform needs comes with the launcher).

- :func:`inventory` ``{id: version | None}``: what the device reports in ``hello`` and ``device status`` shows; a
  tool that is missing or answers another version than pinned is ``None`` for the platform ("not available");
- :func:`ensure` installs what is missing: Playwright's browser for the pinned Playwright (``playwright install
  chromium`` in the launcher's Python), a release archive whose sha256 matches the pinned one, unpacked into
  ``<state>/tools/bin``. pip tools come with the launcher package itself. Nothing is installed system-wide, and a
  failure is a clear message, never a crash of the device service;
- :func:`bin_dirs`: the launcher's own ``bin`` (pip tools) and ``<state>/tools/bin``.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

from .tools_data import TOOLS

TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300


def tools_root(state_root: Path) -> Path:
    return Path(state_root) / "tools"


BROWSERS_ENV = "PLAYWRIGHT_BROWSERS_PATH"


def browsers_path(state_root: Path) -> Path:
    """Where Playwright's own browsers live: the launcher's folder, never ``~/Library/Caches`` (nothing global)."""
    return tools_root(state_root) / "ms-playwright"


def use_own_browsers(state_root: Path) -> None:
    """The launcher's process (its hands-on test) takes Playwright's browsers from the launcher's folder."""
    os.environ.setdefault(BROWSERS_ENV, str(browsers_path(state_root)))


def bin_dirs(state_root: Path) -> list[str]:
    """The folders of the launcher's tools, for the front of a device run's ``PATH``."""
    return [str(Path(sys.executable).parent), str(tools_root(state_root) / "bin")]


def command_env(folder: Path, path: list[str], environment: dict[str, Any] | None = None) -> dict[str, str]:
    """The environment a declared command runs with, in the pipeline and in an agent's wrapped run of it
    (``local_tests.declared_env``): the environment file's ``path`` first, then the launcher's pinned tools (its
    interpreter with Playwright, ast-grep, gitleaks ...), then the system; the browser default and the pytest plugin."""
    from . import browser  # noqa: PLC0415

    env = dict(os.environ)
    dirs = [str((Path(folder) / item).resolve()) for item in path if item]
    env["PATH"] = os.pathsep.join([*dirs, *bin_dirs(default_root()), env.get("PATH", "")])
    env["PIP_REQUIRE_VIRTUALENV"] = "1"
    browser.apply(env, environment)
    return env


def _platform() -> str:
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system(), platform.system().lower())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine(),
                                                                                         platform.machine())
    return f"{system}_{machine}"


def _run(command: list[str], timeout: int = TIMEOUT, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                              env={**os.environ, **(env or {})})
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


def _executable(tool: dict[str, Any], state_root: Path) -> str | None:
    found = shutil.which(str(tool["bin"]), path=os.pathsep.join(bin_dirs(state_root)))
    return found


def _version_of(tool: dict[str, Any], state_root: Path) -> str | None:
    """The pinned version when the tool answers it, else ``None``."""
    pinned = str(tool["version"])
    if tool["source"] == "pip" and not tool.get("bin"):
        from importlib import metadata  # noqa: PLC0415

        try:
            return pinned if metadata.version(str(tool["package"])) == pinned else None
        except metadata.PackageNotFoundError:
            return None
    if tool["source"] == "playwright":
        return pinned if _browser_installed(str(tool["browser"]), state_root) else None
    executable = _executable(tool, state_root)
    if executable is None:
        return None
    code, output = _run([executable, *tool.get("version_args", ["--version"])])
    return pinned if code == 0 and pinned in output else None


def _browser_installed(browser: str, state_root: Path) -> bool:
    """Whether Playwright's own browser for this Playwright version is on disk (its dry run names the folder)."""
    code, output = _run([sys.executable, "-m", "playwright", "install", "--dry-run", browser],
                        env={BROWSERS_ENV: str(browsers_path(state_root))})
    if code != 0:
        return False
    folders = [line.split(":", 1)[1].strip() for line in output.splitlines()
               if line.strip().lower().startswith("install location:")]
    return bool(folders) and all(Path(folder).is_dir() for folder in folders)


def inventory(state_root: Path) -> dict[str, str | None]:
    """``{id: version}`` of the pinned tools this device has, ``None`` for each one it does not."""
    return {str(tool["id"]): _version_of(tool, state_root) for tool in TOOLS}


_CACHE: dict[str, tuple[float, dict[str, str | None]]] = {}
CACHE_SECONDS = 600


def reported(state_root: Path) -> dict[str, str | None]:
    """:func:`inventory`, asked at most every ten minutes (``hello`` and ``state`` report it)."""
    key = str(state_root)
    cached = _CACHE.get(key)
    if cached is None or time.monotonic() - cached[0] > CACHE_SECONDS:
        cached = (time.monotonic(), inventory(state_root))
        _CACHE[key] = cached
    return dict(cached[1])


def _download(tool: dict[str, Any], state_root: Path, fetch: Any) -> str:
    target = _platform()
    digest = dict(tool.get("sha256") or {}).get(target)
    if not digest:
        return f"{tool['id']}: no pinned build for {target}"
    asset = str(dict(tool.get("platforms") or {}).get(target) or target)  # the release's own name for it
    url = str(tool["url"]).format(version=tool["version"], platform=asset)
    limit = int(tool["max_bytes"])
    try:
        data = fetch(url, limit)
    except Exception as error:  # noqa: BLE001 - offline, refused or too large: said, never a crash
        return f"{tool['id']}: download failed ({type(error).__name__}: {str(error)[:120]})"
    if hashlib.sha256(data).hexdigest() != digest:
        return f"{tool['id']}: the download does not match its pinned sha256; nothing was installed"
    folder = tools_root(state_root) / "bin"
    folder.mkdir(parents=True, exist_ok=True)
    if tool.get("archive") == "raw":  # the release asset is the program itself (its size the download's limit)
        return _install(data, folder, str(tool["bin"]))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = next((item for item in archive.getmembers()
                       if item.isfile() and Path(item.name).name == tool["bin"]), None)
        if member is None:
            return f"{tool['id']}: the archive holds no {tool['bin']}"
        if member.size > limit:
            return f"{tool['id']}: {tool['bin']} is larger than {limit} bytes; nothing was installed"
        extracted = archive.extractfile(member)
        body = extracted.read(limit + 1) if extracted is not None else b""
    if len(body) > limit:
        return f"{tool['id']}: {tool['bin']} is larger than {limit} bytes; nothing was installed"
    return _install(body, folder, str(tool["bin"]))


def _install(body: bytes, folder: Path, name: str) -> str:
    """Write next to the target and rename into place; a failure leaves no partial file behind."""
    handle, partial_name = tempfile.mkstemp(dir=folder, prefix=f".{name}.")
    partial = Path(partial_name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(body)
        partial.chmod(0o755)
        partial.replace(folder / name)
    except OSError as error:
        return f"{name}: could not be written ({type(error).__name__}: {str(error)[:120]})"
    finally:
        partial.unlink(missing_ok=True)
    return ""


def _fetch(url: str, max_bytes: int) -> bytes:
    import httpx  # noqa: PLC0415

    chunks: list[bytes] = []
    size = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"larger than {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


ENSURE_FILE = "ensure.json"


def _record_ensure(state_root: Path, data: dict[str, Any]) -> None:
    import json  # noqa: PLC0415

    folder = tools_root(state_root)
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ENSURE_FILE).write_text(json.dumps(data), encoding="utf-8")


def ensure(state_root: Path, fetch: Any = _fetch) -> list[str]:
    """Install the missing tools; the problems as sentences (empty: everything is there). Its progress is kept in
    ``tools/ensure.json`` (:func:`tool_states` reads it)."""
    _record_ensure(state_root, {"pid": os.getpid(), "started": time.time()})
    try:
        problems = _ensure(state_root, fetch)
    except Exception as exc:
        _record_ensure(state_root, {"finished": time.time(), "problems": [f"ensure failed: {type(exc).__name__}"]})
        raise
    _record_ensure(state_root, {"finished": time.time(), "problems": problems})
    return problems


def _ensure(state_root: Path, fetch: Any) -> list[str]:
    problems: list[str] = []
    for tool in TOOLS:
        if _version_of(tool, state_root) is not None:
            continue
        if tool["source"] == "pip":
            problems.append(f"{tool['id']}: missing from the launcher's environment; reinstall the launcher")
        elif tool["source"] == "playwright":
            code, output = _run([sys.executable, "-m", "playwright", "install", str(tool["browser"])],
                                timeout=DOWNLOAD_TIMEOUT, env={BROWSERS_ENV: str(browsers_path(state_root))})
            if code != 0:
                problems.append(f"{tool['id']}: playwright install failed: {output[-200:]}")
        elif problem := _download(tool, state_root, fetch):
            problems.append(problem)
    return problems


INSTALL_COMMAND = "octryx-claude device tools --ensure"


def _running(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tool_states(state_root: Path) -> dict[str, str]:
    """``{id: state}`` for the status: the version, or why it is not there yet (e.g. still being fetched in the
    background right after ``device enable``, ``device_runtime._ensure_tools``)."""
    import json  # noqa: PLC0415

    try:
        record = json.loads((tools_root(state_root) / ENSURE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    record = record if isinstance(record, dict) else {}
    installing = not record.get("finished") and _running(record.get("pid"))
    problems = [str(item) for item in record.get("problems") or []] if record.get("finished") else []
    states: dict[str, str] = {}
    for name, version in inventory(state_root).items():
        failed = next((item for item in problems if item.startswith(f"{name}:")), "")
        states[name] = (version or ("being installed by the device service" if installing
                                    else f"missing ({failed[len(name) + 1:].strip()[:120]}; run: {INSTALL_COMMAND})"
                                    if failed else f"not installed yet (the device service installs it at its start; "
                                    f"or run: {INSTALL_COMMAND})"))
    return states


def default_root() -> Path:
    """The launcher's state folder (``OCTRYX_CLAUDE_HOME``, else the installed default)."""
    return Path(os.environ.get("OCTRYX_CLAUDE_HOME") or Path.home() / ".octryx" / "claude")


__all__ = ["BROWSERS_ENV", "INSTALL_COMMAND", "bin_dirs", "browsers_path", "command_env", "default_root", "ensure",
           "inventory", "reported", "tool_states", "tools_root", "use_own_browsers"]
