"""Where the pet gets the platform URL, a gateway token and its settings directory.

- :class:`LocalAccount` (macOS, Linux): the launcher's own login in the state dir (``get_access_token`` refreshes
  under the credentials lock), settings next to it.
- :class:`WslAccount` (native Windows): octryx-claude itself runs in WSL2 and holds the login there. The pet borrows
  the gateway token through ``wsl.exe -d <distro> -e <home>/.local/bin/octryx-claude api-key-helper`` (the
  token on stdout) and keeps it in memory only, for ``TOKEN_TTL_SECONDS`` or until the platform answers 401: no
  second login, no secret on the Windows side. ``account.json`` (written by install.ps1) holds the platform URL, the
  distribution and the WSL home, nothing secret. The call runs without a console window.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..state import LocalState
from ..tokens import GATEWAY_AUDIENCE, TokenUnavailableError, get_access_token

TOKEN_TTL_SECONDS = 600.0
BRIDGE_TIMEOUT_SECONDS = 60.0
ACCOUNT_FILE = "account.json"
CREATE_NO_WINDOW = 0x08000000  # subprocess flag on Windows: no console window flashes up for wsl.exe
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{16,8192}$")
_DISTRO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WSL_HOME = re.compile(r"^/[A-Za-z0-9._/-]{1,200}$")

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class Account(Protocol):
    root: Path

    def base_url(self) -> str: ...

    def token(self, http: httpx.Client, *, refresh: bool = False) -> str: ...


class LocalAccount:
    def __init__(self, state: LocalState) -> None:
        self.state = state
        self.root = state.root

    def base_url(self) -> str:
        return str(self.state.config().get("base_url") or "").rstrip("/")

    def token(self, http: httpx.Client, *, refresh: bool = False) -> str:
        # get_access_token keeps its own cache and refreshes before expiry; a 401 cannot be fixed here.
        return get_access_token(self.state, GATEWAY_AUDIENCE, http=http)


def windows_root(env: dict[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    base = source.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Octryx" / "octryx-claude" / "pet"


def default_bridge_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=BRIDGE_TIMEOUT_SECONDS, check=False,
                          stdin=subprocess.DEVNULL, creationflags=flags)


class WslAccount:
    def __init__(self, root: Path, *, runner: Runner = default_bridge_runner,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.root = root
        self.runner = runner
        self.clock = clock
        self._token = ""
        self._until = 0.0

    def _config(self) -> dict[str, Any]:
        try:
            value = json.loads((self.root / ACCOUNT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def base_url(self) -> str:
        url = str(self._config().get("base_url") or "").rstrip("/")
        return url if url.startswith(("https://", "http://")) else ""

    def bridge_command(self) -> list[str] | None:
        config = self._config()
        distro, home = str(config.get("wsl_distribution") or ""), str(config.get("wsl_home") or "")
        if not _DISTRO.match(distro) or not _WSL_HOME.match(home):
            return None
        return ["wsl.exe", "-d", distro, "-e", f"{home}/.local/bin/octryx-claude", "api-key-helper"]

    def token(self, http: httpx.Client, *, refresh: bool = False) -> str:
        if self._token and not refresh and self.clock() < self._until:
            return self._token
        self._token, self._until = "", 0.0
        command = self.bridge_command()
        if command is None:
            raise TokenUnavailableError("not_configured")
        try:
            done = self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TokenUnavailableError("wsl_unavailable") from exc
        token = (done.stdout or "").strip()
        if done.returncode != 0 or not _TOKEN.match(token):
            # api-key-helper exits 1 without a login in WSL; anything else (no WSL, no distro) is unavailable.
            raise TokenUnavailableError("not_logged_in" if done.returncode == 1 else "wsl_unavailable")
        self._token, self._until = token, self.clock() + TOKEN_TTL_SECONDS
        return token


def default_account() -> Account:
    """The account of this process: the WSL bridge on native Windows, the launcher's login elsewhere."""
    if os.name == "nt":
        return WslAccount(windows_root())
    return LocalAccount(LocalState().ensure())


__all__ = ["Account", "LocalAccount", "WslAccount", "default_account", "windows_root"]
