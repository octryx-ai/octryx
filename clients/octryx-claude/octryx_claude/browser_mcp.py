"""A browser of its own for one run turn: Microsoft's Playwright MCP server, started by Claude Code for that session.

The story session checks every screen it builds at desktop and phone width in a browser, but "a
browser MCP server that launches its OWN isolated browser instance per session, no extension". The Claude-in-Chrome
route before it (``claude --chrome`` in an agent Chrome profile) needed the extension installed by hand and
could drive the person's own Chrome.

Why ``@playwright/mcp`` and not Google's ``chrome-devtools-mcp`` (both checked with ``--help``):

- ``browser_resize`` sets the exact widths the check needs (1280, 390); ``browser_snapshot`` gives the page as an
  accessibility tree in text, which a small model reads more cheaply than screenshots;
- ``--allowed-origins`` takes ``http://127.0.0.1:*`` with any port; chrome-devtools-mcp's ``--allowedUrlPattern``
  needs Chrome 149+, and it sends usage statistics and page URLs (CrUX) to Google unless switched off;
- ``--browser chrome`` uses the device's installed Google Chrome, so nothing is downloaded; without Chrome the bundled
  Chromium is installed once into the same folder.

How it runs:

- the package is pinned (:data:`VERSION`) and installed once with the device's own ``npm`` into the launcher's state
  folder (``<state>/browser-mcp/<version>``, :func:`ensure_installed`); no global install, no ``npx`` at run time, so a
  turn starts it offline. When ``npm`` or the install is missing, the turn simply has no browser (its prompt falls
  back to Playwright screenshots);
- every session gets a profile folder of its own (``--user-data-dir <state>/sessions/<key>/browser-profile``,
  :func:`profile_dir`; an isolated user-data dir per session under the session folder, never
  the person's Chrome profile; Playwright MCP 0.0.84 refuses ``--isolated`` together with a user-data dir),
  ``--headless`` (no window on the person's screen) and ``--allowed-origins`` for loopback only (none with the offer's
  ``browser_external``, B13: public pages are read, the hooks refuse internal hosts). "The app's ports"
  are any loopback port: no repository declares its app's port (``coding_setup.environment`` has commands only,
  the system tests start the app on a free port), so the session's own app is wherever it listens on
  127.0.0.1/localhost. Only the platform's own port is blocked (``--blocked-origins``, evaluated before the
  allowlist) when the platform itself listens on loopback (a local stack, ``OCTRYX_BASE_URL=http://127.0.0.1:24600``);
- downloads are off (``browser.contextOptions.acceptDownloads = false`` in a per-session ``--config`` file, the only
  way 0.0.84 takes it), and ``file://`` stays blocked (no ``--allow-unrestricted-file-access``);
- its own README says the origin lists do "not serve as a security boundary": the launcher's PreToolUse hook
  (``hooks``, ``run_shell.browser_rule``, for Claude Code and Codex alike) and the platform's rule
  (``workflow_runs/octryx/browser_tools``) are the boundary;
- Codex gets the same server under the same name in its session ``config.toml`` (``codex_driver.config_toml``); the
  name has no ``-``, so its tools are ``mcp__playwright__browser_*`` in both engines;
- its snapshots and screenshots go to a folder of the session outside the state folder (:func:`output_dir`), which the
  agent may read (the state folder is closed to the agent's file tools and sandbox).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import browser

PACKAGE = "@playwright/mcp"
VERSION = "0.0.84"
SERVER_NAME = "playwright"
ALLOWED_ORIGINS = "http://127.0.0.1:*;http://localhost:*;https://127.0.0.1:*;https://localhost:*"
PROFILE_DIR = "browser-profile"
CONFIG_FILE = "browser-mcp-config.json"
# What no CLI option of 0.0.84 sets: a download is never saved (no file arrives on the device from a page).
SERVER_CONFIG = {"browser": {"contextOptions": {"acceptDownloads": False}}}
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
INSTALL_TIMEOUT = 600
NODE_CANDIDATES = ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node")


def install_dir(state_root: Path) -> Path:
    return Path(state_root) / "browser-mcp" / VERSION


def cli_path(folder: Path) -> Path:
    return folder / "node_modules" / "@playwright" / "mcp" / "cli.js"


def find_node() -> str | None:
    """The device's ``node``: on ``PATH``, else where Homebrew and the installers put it (a LaunchAgent's PATH is
    short)."""
    found = shutil.which("node")
    if found:
        return found
    return next((path for path in NODE_CANDIDATES if Path(path).is_file()), None)


def installed_version(folder: Path) -> str:
    try:
        manifest = json.loads((folder / "node_modules" / "@playwright" / "mcp" / "package.json").read_text())
    except (OSError, ValueError):
        return ""
    return str(manifest.get("version") or "") if isinstance(manifest, dict) else ""


def _npm(node: str) -> str | None:
    beside = Path(node).with_name("npm")
    return str(beside) if beside.is_file() else shutil.which("npm")


def ensure_installed(state_root: Path, *, node: str | None = None, run: Any = None) -> Path | None:
    """The pinned server's ``cli.js``, installed into the state folder first when it is not there; ``None`` when it
    cannot be (no ``node`` or ``npm``, offline on the first use, a failed install)."""
    folder = install_dir(state_root)
    if installed_version(folder) == VERSION and cli_path(folder).is_file():
        return cli_path(folder)
    node = node or find_node()
    npm = _npm(node) if node else None
    if not node or not npm:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PATH": os.pathsep.join([str(Path(node).parent), os.environ.get("PATH", "")])}
        (run or subprocess.run)(
            [npm, "install", "--prefix", str(folder), "--no-audit", "--no-fund", "--no-save", "--ignore-scripts",
             f"{PACKAGE}@{VERSION}"],
            cwd=str(folder), env=env, capture_output=True, timeout=INSTALL_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return cli_path(folder) if installed_version(folder) == VERSION and cli_path(folder).is_file() else None


def ensure_chromium(folder: Path, node: str, *, run: Any = None) -> bool:
    """A device without Google Chrome: Playwright's bundled Chromium, installed once into ``<folder>/browsers``."""
    browsers = folder / "browsers"
    if browsers.is_dir() and any(browsers.glob("chromium*")):
        return True
    playwright_cli = folder / "node_modules" / "playwright" / "cli.js"
    if not playwright_cli.is_file():
        return False
    try:
        (run or subprocess.run)([node, str(playwright_cli), "install", "chromium"], cwd=str(folder),
                                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)}, capture_output=True,
                                timeout=INSTALL_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return browsers.is_dir() and any(browsers.glob("chromium*"))


def output_dir(session_key: str) -> Path:
    return browser.cache_root() / "browser" / (session_key or "session")


def session_folder(state_root: Path, session_key: str) -> Path | None:
    """``<state>/sessions/<key>`` (``LocalState.session_dir``); ``None`` for a key that is no UUID."""
    try:
        return Path(state_root) / "sessions" / str(uuid.UUID(str(session_key)))
    except ValueError:
        return None


def profile_dir(state_root: Path, session_key: str) -> Path | None:
    """The browser's own profile for this session only (cookies and storage of the app it looks at)."""
    folder = session_folder(state_root, session_key)
    return folder / PROFILE_DIR if folder is not None else None


def blocked_origins(platform_url: str, *, external: bool = False) -> list[str]:
    """The platform's own origins when it listens on loopback (a local stack), else nothing: the browser looks at the
    session's app, never at the platform. A browser that reads external pages (``external``) also never opens the
    platform's public host."""
    try:
        parts = urlsplit(str(platform_url or "").strip())
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return []
    host = (parts.hostname or "").lower()
    if external and host and host not in (*LOOPBACK_HOSTS, "::1"):
        suffix = f":{parts.port}" if parts.port else ""
        return [f"{scheme}://{host}{suffix}" for scheme in ("http", "https")]
    if host not in (*LOOPBACK_HOSTS, "::1") or not port:
        return []
    return [f"{scheme}://{host}:{port}" for scheme in ("http", "https") for host in LOOPBACK_HOSTS]


def server_spec(state_root: Path, session_key: str, *, node: str | None = None, chrome: bool | None = None,
                install: Any = None, run: Any = None, platform_url: str = "",
                external: bool = False) -> dict[str, Any] | None:
    """The MCP server entry of one session's browser (``mcpServers.playwright``), or ``None`` without one.
    ``external`` (the offer's ``browser_external``, B13): no loopback-only ``--allowed-origins``; the platform's
    origins stay blocked and the hooks' ``run_shell.browser_rule`` refuses internal hosts."""
    profile = profile_dir(state_root, session_key)
    if profile is None:
        return None
    node = node or find_node()
    cli = (install or ensure_installed)(state_root, node=node) if node else None
    if not node or cli is None:
        return None
    folder = install_dir(state_root)
    out = output_dir(session_key)
    config = profile.parent / CONFIG_FILE
    try:
        out.mkdir(parents=True, exist_ok=True)
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.write_text(json.dumps(SERVER_CONFIG), encoding="utf-8")
        os.chmod(config, 0o600)
    except OSError:
        return None
    use_chrome = browser.chrome_installed() if chrome is None else chrome
    if not use_chrome and not ensure_chromium(folder, node, run=run):
        return None
    args = [str(cli), "--headless", "--user-data-dir", str(profile), "--config", str(config),
            "--browser", "chrome" if use_chrome else "chromium",
            *([] if external else ["--allowed-origins", ALLOWED_ORIGINS]),
            "--output-dir", str(out), "--viewport-size", "1280x800"]
    if blocked := blocked_origins(platform_url, external=external):
        args += ["--blocked-origins", ";".join(blocked)]
    # Without Chrome: Playwright's own Chromium, installed once into the same folder (``ensure_chromium``).
    env = {} if use_chrome else {"PLAYWRIGHT_BROWSERS_PATH": str(folder / "browsers")}
    return {"type": "stdio", "command": node, "args": args, **({"env": env} if env else {})}


def browser_config(mcp_path: Path, spec: dict[str, Any]) -> Path:
    """The session's MCP config (``--strict-mcp-config``) with the browser server added, written next to it for this
    turn only (``mcp-browser.json``); the session's own config stays without a browser for every other turn."""
    try:
        config = json.loads(Path(mcp_path).read_text())
    except (OSError, ValueError):
        config = {}
    servers = dict(config.get("mcpServers") or {}) if isinstance(config, dict) else {}
    target = Path(mcp_path).with_name("mcp-browser.json")
    target.write_text(json.dumps({"mcpServers": {**servers, SERVER_NAME: spec}}, indent=2))
    os.chmod(target, 0o600)
    return target


__all__ = ["ALLOWED_ORIGINS", "PACKAGE", "SERVER_NAME", "VERSION", "blocked_origins", "browser_config",
           "ensure_installed", "find_node", "install_dir", "output_dir", "profile_dir", "server_spec"]
