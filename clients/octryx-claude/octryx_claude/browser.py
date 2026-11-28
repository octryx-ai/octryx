"""System tests use the device's installed Google Chrome instead of a Playwright Chromium per repository.
The pytest plugin gets its own folder because Claude Code's sandbox may not read the launcher's state."""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from . import __version__

CHANNEL_ENV = "OCTRYX_BROWSER_CHANNEL"
MISSING_ENV = "OCTRYX_BROWSER_MISSING"
PLUGIN_MODULE = "octryx_pytest"
CHROME = "chrome"
BUNDLED = "chromium"
BROWSERS = (CHROME, BUNDLED)
MAC_CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
LINUX_CHROME = ("google-chrome", "google-chrome-stable", "/opt/google/chrome/chrome")
WINDOWS_CHROME = (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                  r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                  r"%LocalAppData%\Google\Chrome\Application\chrome.exe")
_BROWSER_DOWNLOAD = re.compile(
    r"^\s*(?:\S*/)?(?:python3?(?:\.\d+)?\s+-m\s+)?playwright\s+install(?:\s+--with-deps)?\s+chromium\s*$")


def chrome_installed(platform: str | None = None) -> bool:
    platform = platform or sys.platform
    if platform == "darwin":
        return any(Path(os.path.expanduser(path)).is_file() for path in MAC_CHROME)
    if platform.startswith("win"):
        return any(Path(os.path.expandvars(path)).is_file() for path in WINDOWS_CHROME)
    return any(shutil.which(name) or Path(name).is_file() for name in LINUX_CHROME)


def wanted(environment: Mapping[str, Any] | None) -> str:
    value = str((environment or {}).get("browser") or "").strip().lower()
    return value if value in BROWSERS else CHROME


def cache_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "octryx-claude"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "octryx-claude"


def plugin_dir(root: Path | None = None) -> Path | None:
    folder = (root or cache_root()) / f"pytest-{__version__}"
    source = Path(__file__).with_name(f"{PLUGIN_MODULE}.py")
    target = folder / f"{PLUGIN_MODULE}.py"
    try:
        content = source.read_bytes()
        if not target.is_file() or target.read_bytes() != content:
            folder.mkdir(parents=True, exist_ok=True)
            partial = folder / f".{PLUGIN_MODULE}.{os.getpid()}.tmp"
            partial.write_bytes(content)
            os.replace(partial, target)
    except OSError:
        return None
    return folder


def _prepend(env: MutableMapping[str, str], key: str, value: str, separator: str) -> None:
    parts = [part for part in env.get(key, "").split(separator) if part]
    if value not in parts:
        env[key] = separator.join([value, *parts])


def apply(env: MutableMapping[str, str], environment: Mapping[str, Any] | None = None, *,
          installed: bool | None = None, root: Path | None = None) -> MutableMapping[str, str]:
    if not env.get(CHANNEL_ENV, "").strip():
        env.pop(CHANNEL_ENV, None)
        env.pop(MISSING_ENV, None)
        if wanted(environment) == CHROME:
            if chrome_installed() if installed is None else installed:
                env[CHANNEL_ENV] = CHROME
            else:
                env[MISSING_ENV] = CHROME
    folder = plugin_dir(root)
    if folder is not None:
        _prepend(env, "PYTHONPATH", str(folder), os.pathsep)
        _prepend(env, "PYTEST_PLUGINS", PLUGIN_MODULE, ",")
    return env


def skips_setup(command: str, env: Mapping[str, str]) -> bool:
    return env.get(CHANNEL_ENV) == CHROME and bool(_BROWSER_DOWNLOAD.match(command or ""))


__all__ = ["BROWSERS", "CHANNEL_ENV", "MISSING_ENV", "PLUGIN_MODULE", "apply", "cache_root", "chrome_installed",
           "plugin_dir", "skips_setup", "wanted"]
