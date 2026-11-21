"""System tests use the device's installed Google Chrome, not a Playwright Chromium downloaded per repository.

The Chrome already installed replaces a browser download per repository and per item worktree, and the agents'
conftests launch ``p.chromium.launch()`` without knowing about it.

So the platform default is the system Chrome (Playwright's ``channel="chrome"``), applied to every test run on the
device without the agent knowing anything about it:

- the agent's session, the pipeline and the environment setup get ``OCTRYX_BROWSER_CHANNEL=chrome`` and the pytest
  plugin ``octryx_pytest`` (``PYTEST_PLUGINS`` plus its folder on ``PYTHONPATH``), which gives a Chromium launch
  without its own channel the device's Chrome (``octryx_pytest``);
- a repository that wants Playwright's bundled browser says so: ``coding_setup.environment.browser = "chromium"``
  (then nothing changes and its own ``playwright install chromium`` runs as declared);
- no Chrome on the device: ``OCTRYX_BROWSER_MISSING`` makes a failed launch say what to install or declare, instead
  of Playwright's "Executable doesn't exist"; a person's own ``OCTRYX_BROWSER_CHANNEL`` always wins;
- with Chrome as the browser, a declared setup step that only downloads Playwright's Chromium is skipped
  (:func:`skips_setup`): the repository may drop it, and until it does nothing is downloaded per worktree.

The plugin is copied into a folder of its own outside the launcher's state (:func:`plugin_dir`), because Claude
Code's sandbox may not read that state and the repository's interpreter has no octryx-claude installed.
"""

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
    """Whether Google Chrome is installed where Playwright's ``chrome`` channel looks for it."""
    platform = platform or sys.platform
    if platform == "darwin":
        return any(Path(os.path.expanduser(path)).is_file() for path in MAC_CHROME)
    if platform.startswith("win"):
        return any(Path(os.path.expandvars(path)).is_file() for path in WINDOWS_CHROME)
    return any(shutil.which(name) or Path(name).is_file() for name in LINUX_CHROME)


def wanted(environment: Mapping[str, Any] | None) -> str:
    """The repository's browser: ``chrome`` (the default) or ``chromium`` (Playwright's bundled one)."""
    value = str((environment or {}).get("browser") or "").strip().lower()
    return value if value in BROWSERS else CHROME


def cache_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "octryx-claude"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "octryx-claude"


def plugin_dir(root: Path | None = None) -> Path | None:
    """The folder that holds only the pytest plugin, written once per launcher version; ``None`` when it cannot be
    written (the test runs then simply go without it)."""
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
    """Put the browser default and the pytest plugin into ``env`` (in place) and return it."""
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
    """A declared setup step that only downloads Playwright's Chromium, while the runs use the device's Chrome."""
    return env.get(CHANNEL_ENV) == CHROME and bool(_BROWSER_DOWNLOAD.match(command or ""))


__all__ = ["BROWSERS", "CHANNEL_ENV", "MISSING_ENV", "PLUGIN_MODULE", "apply", "cache_root", "chrome_installed",
           "plugin_dir", "skips_setup", "wanted"]
