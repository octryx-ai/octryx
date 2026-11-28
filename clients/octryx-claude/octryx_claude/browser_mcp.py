"""Playwright MCP as an isolated, headless, loopback-only browser for one run turn.
Its origin lists are no security boundary: the PreToolUse hook and the platform's browser rule are."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import browser, state

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
# A server runner has no internet: its image carries the pinned server and its Chromium here, read-only.
PREBUILT_ENV = "OCTRYX_BROWSER_MCP_DIR"
OUTPUT_DIR = "browser-output"


def install_dir(state_root: Path) -> Path:
    prebuilt = os.environ.get(PREBUILT_ENV, "")
    return Path(prebuilt) if prebuilt else Path(state_root) / "browser-mcp" / VERSION


def cli_path(folder: Path) -> Path:
    return folder / "node_modules" / "@playwright" / "mcp" / "cli.js"


def find_node() -> str | None:
    # A LaunchAgent's PATH is short, so Homebrew's and the installers' locations are tried too.
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
    folder = install_dir(state_root)
    if installed_version(folder) == VERSION and cli_path(folder).is_file():
        return cli_path(folder)
    if os.environ.get(PREBUILT_ENV):
        return None
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
    try:
        return Path(state_root) / "sessions" / str(uuid.UUID(str(session_key)))
    except ValueError:
        return None


def profile_dir(state_root: Path, session_key: str) -> Path | None:
    folder = session_folder(state_root, session_key)
    return folder / PROFILE_DIR if folder is not None else None


def blocked_origins(platform_url: str, *, external: bool = False) -> list[str]:
    # The browser looks at the session's app, never at the platform.
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
    profile = profile_dir(state_root, session_key)
    if profile is None:
        return None
    node = node or find_node()
    cli = (install or ensure_installed)(state_root, node=node) if node else None
    if not node or cli is None:
        return None
    folder = install_dir(state_root)
    # On a server runner the browser runs under the agent's account: its folders are the shared state's group's.
    shared = state.shared_state()
    out = profile.parent / OUTPUT_DIR if shared else output_dir(session_key)
    config = profile.parent / CONFIG_FILE
    try:
        out.mkdir(parents=True, exist_ok=True)
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        if shared:
            for path in (out, profile):
                os.chmod(path, 0o2770)
        config.write_text(json.dumps(SERVER_CONFIG), encoding="utf-8")
        os.chmod(config, 0o640 if shared else 0o600)
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
