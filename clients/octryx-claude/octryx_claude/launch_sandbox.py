"""Claude Code's OS sandbox for a session: what Bash may read and which hosts it may reach.

Bash runs in Claude Code's OS sandbox (``failIfUnavailable``: no sandbox, no session): it can neither read the
octryx state directory (tokens, hook socket) nor reach the platform host, so the agent's own commands cannot mint
or redeem confirmations.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from octryx_claude import local_tests_words

MAX_SANDBOX_DOMAINS = 200
_SANDBOX_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_SANDBOX_DOMAIN = re.compile(rf"^(?:\*\.)?{_SANDBOX_LABEL}(?:\.{_SANDBOX_LABEL})+$")


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _allowed_domains(policy: Mapping[str, Any], denied: list[str]) -> list[str]:
    """The Workspace's sandbox domains from the client policy; malformed or platform entries are dropped."""
    sandbox = policy.get("sandbox") if isinstance(policy.get("sandbox"), Mapping) else {}
    raw = sandbox.get("allowed_domains") if isinstance(sandbox, Mapping) else None
    if not isinstance(raw, list):
        return []
    allowed: list[str] = []
    for entry in raw[:MAX_SANDBOX_DOMAINS]:
        if not isinstance(entry, str) or not _SANDBOX_DOMAIN.fullmatch(entry):
            continue
        if entry.removeprefix("*.") in denied or entry in allowed:
            continue
        allowed.append(entry)
    return allowed


SANDBOX_NETWORK_OPEN = "open"
SANDBOX_NETWORK_ASK_TOOL = "SandboxNetworkAccess"


def sandbox_network(policy: Mapping[str, Any] | None) -> str:
    """The client policy's ``sandbox.network``: ``open`` or ``allowlist`` (absent or unknown: ``allowlist``).

    : allow by default, block as an admin option. Claude Code 2.1.318 refuses ``*`` in
    ``sandbox.network.allowedDomains`` ("Overly broad patterns like "*.com" or "*" are not allowed"), also when it
    comes from a ``WebFetch(domain:*)`` rule, so ``open`` keeps the same lists and the device turn answers the
    sandbox's own question for a host outside them (``SandboxNetworkAccess``) with allow (``device_sdk``)."""
    sandbox = (policy or {}).get("sandbox") if isinstance((policy or {}).get("sandbox"), Mapping) else {}
    value = sandbox.get("network") if isinstance(sandbox, Mapping) else None
    return SANDBOX_NETWORK_OPEN if value == SANDBOX_NETWORK_OPEN else "allowlist"


MAX_UNSANDBOXED = 10
TEST_RUN_SHIM_ENV = "OCTRYX_TEST_RUN_SHIM"


def _unsandboxed_commands(policy: Mapping[str, Any]) -> list[str]:
    """The Workspace's declared system test commands (client policy ``sandbox.unsandboxed_commands``).

    : inside Claude Code's sandbox the app under test cannot bind a port and Chromium cannot start
    (mach port denied); the agent then marked every system test as skipped. The declared command runs outside the
    sandbox; the platform's PreToolUse check still allows it in a phase only verbatim."""
    sandbox = policy.get("sandbox") if isinstance(policy.get("sandbox"), Mapping) else {}
    raw = sandbox.get("unsandboxed_commands") if isinstance(sandbox, Mapping) else None
    if not isinstance(raw, list):
        return []
    found: list[str] = []
    for entry in raw[:MAX_UNSANDBOXED]:
        if isinstance(entry, str) and 0 < len(entry.strip()) <= 300 and entry.strip() not in found:
            found.append(entry.strip())
    return found


def sandbox_settings(*, state_root: Path, base_url: str, policy: Mapping[str, Any] | None = None,
                     shim: Path | None = None) -> dict[str, Any]:
    """Bash cannot read the state directory or talk to the platform directly.

    ``excludedCommands``: the launcher's test-run wrapper (``local_tests``: a run phase's test runs, in any form,
    reach the app and start the device's Chrome outside the sandbox; the wrapper runs nothing else) and the
    Workspace's declared system test commands.

    ``network.allowedDomains`` is the Workspace's admin-edited list (``sandbox.allowed_domains`` of
    the client policy) for builds and package registries. It is empty unless the Workspace sets it,
    in which case Claude Code asks per domain. The platform host stays denied either way, also with
    ``sandbox.network: open`` (:func:`sandbox_network`).
    """
    host = (urlparse(base_url).hostname or "").lower()
    denied = [host] if host else []
    if _is_loopback(host):
        denied += [name for name in ("localhost", "127.0.0.1") if name not in denied]
    # A dev server or test fixture listens on localhost (Packmate system tests).
    network: dict[str, Any] = {"deniedDomains": denied, "allowLocalBinding": True}
    allowed = _allowed_domains(policy or {}, denied)
    if allowed:
        network["allowedDomains"] = allowed
    settings: dict[str, Any] = {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {"denyRead": [str(state_root)]},
        "network": network,
    }
    excluded = [local_tests_words.excluded_pattern(shim)] if shim is not None else []
    excluded += _unsandboxed_commands(policy or {})
    if excluded:
        settings["excludedCommands"] = excluded
    return settings
