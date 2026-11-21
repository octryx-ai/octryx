"""The octryx-claude installer scripts, filled for this platform.

The templates live with the client (``clients/octryx-claude/installer``). Three placeholders are
filled: the platform base URL (the same origin the OAuth issuer uses), an optional Workspace to
preselect at login, and the operating system's own file names (``.DS_Store``, ``Thumbs.db``, ...) from the
launcher's ``octryx_claude/os_junk.json``, so uninstall can remove a folder it created that holds only those.
All three are validated against a quote-free character set before they go into the scripts, where they
sit inside single-quoted string literals, so a request can never inject shell or PowerShell code.
Nothing secret is ever filled in. Stdlib only (the installer tests import it without the app).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .artifact import ClientArtifactError, default_client_dir

BASE_URL_PLACEHOLDER = "@@OCTRYX_BASE_URL@@"
WORKSPACE_PLACEHOLDER = "@@OCTRYX_WORKSPACE@@"
OS_JUNK_PLACEHOLDER = "@@OCTRYX_OS_JUNK@@"
INSTALL_SH = "install.sh"
INSTALL_PS1 = "install.ps1"
SCRIPTS = (INSTALL_SH, INSTALL_PS1)
_HOST = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*" \
        r"|\[[0-9A-Fa-f:.]+\])"
_BASE_URL = re.compile(rf"^https?://{_HOST}(?::[0-9]{{1,5}})?(?:/[A-Za-z0-9._~-]+)*$")
# Workspace ids are UUIDs; names are allowed when they stay in this quote- and space-free set.
_WORKSPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
# File names and simple patterns ("._*"): quote-, space- and bracket-free, so they sit safely in a quoted literal.
_OS_JUNK_NAME = re.compile(r"^[A-Za-z0-9._*-]{1,64}$")


class InstallerRenderError(Exception):
    """The script cannot be produced; ``code`` is fixed (``workspace_invalid``, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def valid_base_url(value: str) -> bool:
    return bool(_BASE_URL.fullmatch(value or ""))


def valid_workspace(value: str) -> bool:
    return bool(_WORKSPACE.fullmatch(value or ""))


def os_junk_files(client_dir: Path | None = None) -> str:
    """The operating system's own file names from ``os_junk.json``, space-separated, for the scripts."""
    path = (client_dir or default_client_dir()) / "octryx_claude" / "os_junk.json"
    try:
        names = json.loads(path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ClientArtifactError("octryx_client_source_missing") from exc
    if not isinstance(names, list) or not all(isinstance(n, str) and _OS_JUNK_NAME.fullmatch(n) for n in names):
        raise InstallerRenderError("installer_template_invalid")
    return " ".join(names)


def render(template: str, *, base_url: str, workspace: str = "", os_junk: str | None = None) -> str:
    base_url = (base_url or "").rstrip("/")
    if not valid_base_url(base_url):
        raise InstallerRenderError("base_url_unusable")
    if workspace and not valid_workspace(workspace):
        raise InstallerRenderError("workspace_invalid")
    if BASE_URL_PLACEHOLDER not in template or WORKSPACE_PLACEHOLDER not in template:
        raise InstallerRenderError("installer_template_invalid")
    script = template.replace("\r\n", "\n")
    script = script.replace(BASE_URL_PLACEHOLDER, base_url).replace(WORKSPACE_PLACEHOLDER, workspace)
    if OS_JUNK_PLACEHOLDER in script:
        script = script.replace(OS_JUNK_PLACEHOLDER, os_junk_files() if os_junk is None else os_junk)
    if "@@OCTRYX_" in script:
        raise InstallerRenderError("installer_template_invalid")
    return script


def installer_template(name: str, client_dir: Path | None = None) -> str:
    if name not in SCRIPTS:
        raise InstallerRenderError("installer_unknown")
    path = (client_dir or default_client_dir()) / "installer" / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientArtifactError("octryx_client_source_missing") from exc


def install_url(base_url: str, name: str, workspace: str = "") -> str:
    url = f"{base_url.rstrip('/')}/octryx-claude/{name}"
    return f"{url}?workspace={workspace}" if workspace else url


def install_commands(base_url: str, workspace: str = "") -> dict[str, str]:
    """The copy-paste one-liners for macOS/Linux/WSL2 and Windows."""
    return {
        "macos": f"curl -fsSL '{install_url(base_url, INSTALL_SH, workspace)}' | bash",
        "windows": f"irm '{install_url(base_url, INSTALL_PS1, workspace)}' | iex",
    }
