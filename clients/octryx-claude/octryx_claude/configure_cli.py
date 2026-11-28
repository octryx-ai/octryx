"""``octryx-claude configure --base-url URL [--workspace ID|NAME]``: remember the platform without signing in."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any
from urllib.parse import urlparse

from .state import LocalState

REQUEST_KEY = "workspace_request"
# A Workspace id or name as the user typed it: printable, one line, bounded.
_WORKSPACE = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")


def _valid_workspace(value: str) -> bool:
    return bool(_WORKSPACE.match(value))


def normalized_base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    return url


def pending_workspace(config: dict[str, Any]) -> str:
    value = str(config.get(REQUEST_KEY) or "").strip()
    return value if _valid_workspace(value) else ""


def add_parser(sub: argparse._SubParsersAction) -> None:
    configure = sub.add_parser("configure", help="remember the platform (and Workspace) without signing in")
    configure.add_argument("--base-url", required=True)
    configure.add_argument("--workspace", default="", help="Workspace id or name, selected at the next login")


def run_configure_command(args: argparse.Namespace, state: LocalState) -> int:
    base_url = normalized_base_url(args.base_url)
    if not base_url:
        sys.stderr.write("octryx-claude: needs_configuration: base_url_invalid (pass --base-url https://...)\n")
        return 2
    workspace = (args.workspace or "").strip()
    if workspace and not _valid_workspace(workspace):
        sys.stderr.write("octryx-claude: denied: workspace_invalid\n")
        return 2
    config = state.config()
    if config.get("base_url") and config.get("base_url") != base_url:
        for key in ("workspace_id", "workspace_name", REQUEST_KEY):
            config.pop(key, None)
    config["base_url"] = base_url
    if workspace:
        config[REQUEST_KEY] = workspace
    state.write_config(config)
    print(f"Configured {base_url}." + (f" Workspace {workspace} is selected at the next login." if workspace else ""))
    return 0
